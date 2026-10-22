"""Offline persistent-memory harness for Challenge A.

The module deliberately separates durable storage from injected context.  A
caller records project conventions, then every new session retrieves only the
active revisions and passes that payload to the agent-response function.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:
    import fcntl


SCHEMA_VERSION = 1
LOCK_WAIT_MILLISECONDS = 5_000
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_GEMINI_TOOL_ROUNDS = 2
AUTHORITATIVE_POLICY = (
    "Active conventions are authoritative. Superseded conventions are audit-only "
    "and must not be followed."
)
TOKEN_PATTERN = re.compile(r"[^\W_]+", re.UNICODE)
CONVENTION_TOPIC_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}")
SENSITIVE_CONVENTION_TOPIC = re.compile(
    r"(?:api_?key|secret|password|credential|private_?key|(?:^|_)token(?:_|$))", re.IGNORECASE
)
SENSITIVE_CONVENTION_VALUE = re.compile(
    r"""(?:
        AIza[\w-]{20,} |
        -----BEGIN |
        (?:api[ _-]?key|secret|password|credential|private[ _-]?key)\s*[:=] |
        gh[pousr]_[A-Za-z0-9_]{20,} |
        github_pat_[A-Za-z0-9_]{20,} |
        sk-(?:proj-)?[A-Za-z0-9_-]{20,} |
        xox[baprs]-[A-Za-z0-9-]{10,} |
        AKIA[A-Z0-9]{16} |
        \beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,} |
        \bBearer\s+[A-Za-z0-9._-]{20,}
    )""",
    re.IGNORECASE | re.VERBOSE,
)


class GeminiError(RuntimeError):
    """A safe, user-facing error raised while using the optional Gemini provider."""


class SensitiveMemoryError(ValueError):
    """Raised before a credential-shaped value reaches durable memory or audit."""


def now_utc() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def validate_timestamp(value: str, field_name: str) -> None:
    """Reject timestamps that cannot be compared reliably in the audit trail."""
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")


def _tokens(value: str) -> set[str]:
    """Split human text and identifiers into stable, Unicode-aware search tokens."""
    normalized = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", value).replace("_", " ")
    return {token.casefold() for token in TOKEN_PATTERN.findall(normalized)}


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def load_local_gemini_environment(path: Path | None = None) -> None:
    """Load only Gemini settings from a local .env without adding a dependency.

    Environment variables already supplied by the shell always win. This deliberately
    supports only simple KEY=VALUE lines so it never evaluates shell syntax.
    """
    env_path = path or Path(__file__).resolve().with_name(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (item.strip() for item in line.split("=", 1))
        if key not in {"GEMINI_API_KEY", "GEMINI_MODEL"} or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            os.environ[key] = value


def validate_memory_write(topic: str, value: str) -> None:
    """Reject credential-shaped data before it can reach store or audit files."""
    if SENSITIVE_CONVENTION_TOPIC.search(topic) or SENSITIVE_CONVENTION_VALUE.search(value):
        raise SensitiveMemoryError("Credentials and secrets cannot be stored as memory")


class MemoryStore:
    """A tiny revisioned JSON memory store plus an append-only audit log."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        # memory.json keeps the friendly legacy name memory-audit.jsonl; other
        # store names receive their own audit file instead of mixing histories.
        self.audit_path = self.path.with_name(f"{self.path.stem}-audit.jsonl")
        self.last_audit_error: str | None = None

    def _empty(self) -> dict[str, Any]:
        return {"schema_version": SCHEMA_VERSION, "conventions": []}

    def load(self) -> dict[str, Any]:
        if self.path.exists() and self.path.is_dir():
            raise ValueError(f"Memory store must be a file path: {self.path}")
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Memory file is not valid JSON: {self.path}") from exc
        schema_version = payload.get("schema_version") if isinstance(payload, dict) else None
        if (
            not isinstance(payload, dict)
            or isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version != SCHEMA_VERSION
            or not isinstance(payload.get("conventions"), list)
        ):
            raise ValueError(f"Unsupported memory schema in {self.path}")
        active_topics: set[str] = set()
        versions_by_topic: dict[str, set[int]] = {}
        supersession_links: list[tuple[str, int]] = []
        required = {"topic", "value", "version", "status", "recorded_at", "source_session"}
        for revision in payload["conventions"]:
            if not isinstance(revision, dict) or not required.issubset(revision):
                raise ValueError(f"Malformed convention revision in {self.path}")
            topic = revision["topic"]
            value = revision["value"]
            source_session = revision["source_session"]
            if not all(
                isinstance(field, str) and field.strip()
                for field in (topic, value, source_session)
            ):
                raise ValueError(f"Convention fields must be non-empty strings in {self.path}")
            if not isinstance(revision["status"], str) or revision["status"] not in {
                "active",
                "superseded",
            }:
                raise ValueError(f"Unknown convention status in {self.path}")
            version = revision["version"]
            if isinstance(version, bool) or not isinstance(version, int) or version < 1:
                raise ValueError(f"Invalid convention version in {self.path}")
            validate_timestamp(revision["recorded_at"], "recorded_at")
            versions = versions_by_topic.setdefault(topic, set())
            if version in versions:
                raise ValueError(f"Duplicate convention version for {topic} in {self.path}")
            versions.add(version)
            if revision["status"] == "active":
                if topic in active_topics:
                    raise ValueError(f"Multiple active revisions for {topic} in {self.path}")
                active_topics.add(topic)
            else:
                superseded_by = revision.get("superseded_by")
                if (
                    isinstance(superseded_by, bool)
                    or not isinstance(superseded_by, int)
                    or superseded_by <= version
                ):
                    raise ValueError(f"Invalid supersession link in {self.path}")
                validate_timestamp(revision.get("superseded_at"), "superseded_at")
                supersession_links.append((topic, superseded_by))
        for topic, target_version in supersession_links:
            if target_version not in versions_by_topic[topic]:
                raise ValueError(f"Supersession target is missing for {topic} in {self.path}")
        return payload

    def _mutex_name(self) -> str:
        canonical_path = str(self.path.resolve(strict=False)).casefold()
        digest = hashlib.sha256(canonical_path.encode("utf-8")).hexdigest()
        return f"Local\\ChallengeAMemory-{digest}"

    @contextmanager
    def _windows_mutex_lock(self) -> Any:
        """Use a named Windows mutex, automatically released after a crash."""
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
        kernel32.ReleaseMutex.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL

        handle = kernel32.CreateMutexW(None, False, self._mutex_name())
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        acquired = False
        try:
            result = kernel32.WaitForSingleObject(handle, LOCK_WAIT_MILLISECONDS)
            wait_object_0, wait_abandoned, wait_timeout = 0, 0x80, 0x102
            if result == wait_timeout:
                raise TimeoutError(f"Memory store is busy: {self.path}")
            if result not in {wait_object_0, wait_abandoned}:
                raise ctypes.WinError(ctypes.get_last_error())
            acquired = True
            yield
        finally:
            if acquired:
                kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)

    @contextmanager
    def _posix_file_lock(self) -> Any:
        """Use an advisory lock where Windows named mutexes are unavailable."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_name(f".{self.path.name}.lock")
        deadline = time.monotonic() + LOCK_WAIT_MILLISECONDS / 1_000
        with lock_path.open("a+", encoding="ascii") as lock_file:
            while True:
                try:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"Memory store is busy: {self.path}")
                    time.sleep(0.05)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @contextmanager
    def _write_lock(self) -> Any:
        """Serialize writes without a stale-lock recovery race."""
        if os.name == "nt":
            with self._windows_mutex_lock():
                yield
        else:
            with self._posix_file_lock():
                yield

    def _save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{uuid.uuid4().hex}.tmp")
        with temporary.open("w", encoding="utf-8") as memory_file:
            memory_file.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            memory_file.flush()
            os.fsync(memory_file.fileno())
        os.replace(temporary, self.path)

    def _append_audit(self, event: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            audit_file.flush()
            os.fsync(audit_file.fileno())

    def _write_audit_best_effort(self, event: dict[str, Any]) -> None:
        """The durable convention is authoritative; surface audit failure clearly."""
        self.last_audit_error = None
        try:
            self._append_audit(event)
        except OSError as exc:
            self.last_audit_error = str(exc)

    def record(
        self, topic: str, value: str, session: str, recorded_at: str | None = None
    ) -> dict[str, Any]:
        """Create a revision; a changed value supersedes the prior active revision."""
        if not all(isinstance(field, str) for field in (topic, value, session)):
            raise ValueError("topic, value, and session must be strings")
        topic, value, session = topic.strip(), value.strip(), session.strip()
        if not topic or not value or not session:
            raise ValueError("topic, value, and session must be non-empty")
        validate_memory_write(topic, value)

        timestamp = now_utc() if recorded_at is None else recorded_at
        validate_timestamp(timestamp, "recorded_at")

        with self._write_lock():
            data = self.load()
            same_topic = [item for item in data["conventions"] if item["topic"] == topic]
            active = next((item for item in same_topic if item["status"] == "active"), None)

            if active and active["value"] == value:
                event = {
                    "event": "convention_confirmed", "topic": topic, "value": value,
                    "version": active["version"], "session": session, "at": timestamp,
                }
                self._write_audit_best_effort(event)
                return active

            version = max((item["version"] for item in same_topic), default=0) + 1
            revision: dict[str, Any] = {
                "topic": topic, "value": value, "version": version, "status": "active",
                "recorded_at": timestamp, "source_session": session,
            }
            if active:
                active["status"] = "superseded"
                active["superseded_at"] = timestamp
                active["superseded_by"] = version

            data["conventions"].append(revision)
            self._save(data)
            self._write_audit_best_effort(
                {
                    "event": "convention_updated" if active else "convention_recorded",
                    "topic": topic, "value": value, "version": version, "session": session,
                    "at": timestamp, "supersedes_version": active["version"] if active else None,
                }
            )
            return revision

    def active_conventions(self) -> list[dict[str, Any]]:
        """Return the compact index that may be injected into a new context."""
        data = self.load()
        return sorted(
            (item for item in data["conventions"] if item["status"] == "active"),
            key=lambda item: item["topic"],
        )

    def retrieve_conventions(
        self,
        task: str,
        topics: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Select active conventions relevant to a task without loading all memory.

        Explicit topic selection is deterministic. Otherwise, relevance is a small
        keyword-overlap ranker so the offline harness needs neither embeddings nor
        another model call just to retrieve context.
        """
        if not isinstance(task, str) or not task.strip():
            raise ValueError("task must be a non-empty string")
        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ValueError("memory limit must be a positive integer")

        active = self.active_conventions()
        requested_topics = None
        if topics is not None:
            requested_topics = {
                topic.strip() for topic in topics if isinstance(topic, str) and topic.strip()
            }
            selected = [item for item in active if item["topic"] in requested_topics]
        else:
            task_tokens = _tokens(task)
            ranked: list[tuple[int, str, dict[str, Any]]] = []
            for item in active:
                convention_tokens = _tokens(f"{item['topic']} {item['value']}")
                score = len(task_tokens & convention_tokens)
                if score:
                    ranked.append((score, item["topic"], item))
            selected = [item for _, _, item in sorted(ranked, key=lambda entry: (-entry[0], entry[1]))]
            # With exactly one known convention there is no context-bloat trade-off,
            # and retaining it preserves a useful first-project default.
            if not selected and len(active) == 1:
                selected = active
        return selected[:limit] if limit is not None else selected

    def injected_memory(
        self,
        task: str | None = None,
        topics: Iterable[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Return all active memory by default, or a selected subset for an ask."""
        if task is None and topics is None and limit is None:
            conventions = self.active_conventions()
        elif topics is not None:
            conventions = self.retrieve_conventions(task or "explicit topic selection", topics, limit)
        elif task is not None:
            conventions = self.retrieve_conventions(task, limit=limit)
        else:
            conventions = self.active_conventions()[:limit]
        return {
            "kind": "persistent_project_memory",
            "policy": AUTHORITATIVE_POLICY,
            "conventions": [
                {
                    "topic": item["topic"],
                    "value": item["value"],
                    "version": item["version"],
                    "source_session": item["source_session"],
                }
                for item in conventions
            ],
        }

    def record_retrieval(self, session: str, payload: dict[str, Any]) -> None:
        """Keep a small audit record that a particular session received this context."""
        if not isinstance(session, str) or not session.strip():
            raise ValueError("session must be non-empty")
        self._write_audit_best_effort(
            {
                "event": "memory_injected",
                "session": session,
                "at": now_utc(),
                "conventions": [
                    {"topic": item["topic"], "version": item["version"]}
                    for item in payload["conventions"]
                ],
            }
        )


def format_injected_memory(payload: dict[str, Any]) -> str:
    return "--- INJECTED_MEMORY ---\n" + json.dumps(
        payload, ensure_ascii=False, indent=2
    ) + "\n--- END_INJECTED_MEMORY ---"


def agent_response(task: str, injected_memory: dict[str, Any]) -> str:
    """Offline agent stub whose decision is derived solely from injected memory.

    Replacing this function with an LLM API call would preserve the important
    boundary: pass `format_injected_memory(payload)` as part of the prompt.
    """
    conventions = {item["topic"]: item for item in injected_memory["conventions"]}
    style = conventions.get("api_field_style")
    if style is None:
        return f"No API-field convention was injected. Task noted: {task}"

    if style["value"] == "camelCase":
        example = '{ "userId": 1, "createdAt": "2026-10-21T00:00:00Z" }'
    elif style["value"] == "snake_case":
        example = '{ "user_id": 1, "created_at": "2026-10-21T00:00:00Z" }'
    else:
        example = f"Apply the injected style `{style['value']}` consistently."
    return (
        f"Session follows api_field_style v{style['version']} = {style['value']}. "
        f"For '{task}', use: {example}"
    )


def build_gemini_prompt(task: str, injected_memory: dict[str, Any]) -> str:
    """Build the exact context submitted to Gemini after it has been printed locally."""
    return (
        "You are a project assistant. Follow only active conventions supplied in the "
        "persistent-memory block. Answer the user task directly. If, and only if, the "
        "user explicitly confirms or changes a durable project convention, call "
        "remember_convention. Never store transient requests, guesses, credentials, "
        "or chat logs.\n\n"
        f"{format_injected_memory(injected_memory)}\n\n"
        f"USER_TASK:\n{task}"
    )


REMEMBER_CONVENTION_TOOL = {
    "functionDeclarations": [
        {
            "name": "remember_convention",
            "description": (
                "Persist a durable project convention only after the user explicitly "
                "confirms or changes it. Never save credentials, secrets, transient "
                "requests, guesses, or chat logs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Stable snake_case convention name."},
                    "value": {"type": "string", "description": "Confirmed convention value."},
                },
                "required": ["topic", "value"],
            },
        }
    ]
}


def _gemini_transport(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:
        return response.read()


class GeminiClient:
    """Small dependency-free Gemini REST client with an injectable test transport."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        transport: Callable[[Request], bytes] | None = None,
    ) -> None:
        load_local_gemini_environment()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL)
        self.transport = transport or _gemini_transport
        if not self.api_key:
            raise GeminiError(
                "GEMINI_API_KEY is required for --provider gemini. "
                "Copy .env.example to .env or set the environment variable."
            )

    def generate(
        self, contents: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        model = self.model.removeprefix("models/")
        url = GEMINI_API_URL.format(model=quote(model, safe="-._"))
        payload: dict[str, Any] = {"contents": contents}
        if tools:
            payload["tools"] = tools
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            raw_response = self.transport(request)
            response = json.loads(raw_response.decode("utf-8"))
        except HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = str(payload.get("error", {}).get("message", "")).strip()
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, AttributeError):
                pass
            suffix = f": {detail}" if detail else ""
            raise GeminiError(f"Gemini API request failed ({exc.code}){suffix}") from exc
        except URLError as exc:
            raise GeminiError(f"Could not reach Gemini API: {exc.reason}") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini API returned an unreadable response") from exc
        if not isinstance(response, dict):
            raise GeminiError("Gemini API returned an invalid response")
        return response


def _gemini_candidate_content(response: dict[str, Any]) -> dict[str, Any]:
    candidates = response.get("candidates")
    if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
        content = candidates[0].get("content")
        if isinstance(content, dict) and isinstance(content.get("parts"), list):
            return content
        finish_reason = candidates[0].get("finishReason", "unknown")
        raise GeminiError(f"Gemini returned no usable content (finish reason: {finish_reason})")
    feedback = response.get("promptFeedback")
    block_reason = feedback.get("blockReason") if isinstance(feedback, dict) else None
    if block_reason:
        raise GeminiError(f"Gemini blocked the request: {block_reason}")
    raise GeminiError("Gemini returned no candidates")


def _gemini_text(content: dict[str, Any]) -> str:
    return "".join(
        part["text"]
        for part in content["parts"]
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ).strip()


def _remember_result(
    store: MemoryStore, session: str, arguments: Any, allow_memory_write: bool
) -> dict[str, Any]:
    if not allow_memory_write:
        return {
            "ok": False,
            "error": "Model memory writes are disabled. Re-run with --allow-memory-write after confirmation.",
        }
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "Tool arguments must be an object."}
    topic, value = arguments.get("topic"), arguments.get("value")
    if not isinstance(topic, str) or not isinstance(value, str):
        return {"ok": False, "error": "topic and value must be strings."}
    topic, value = topic.strip(), value.strip()
    if not CONVENTION_TOPIC_PATTERN.fullmatch(topic):
        return {"ok": False, "error": "topic must be lowercase snake_case (up to 64 characters)."}
    if not value or len(value) > 500:
        return {"ok": False, "error": "value must contain 1 to 500 characters."}
    try:
        revision = store.record(topic, value, session)
    except SensitiveMemoryError:
        return {"ok": False, "error": "Credentials and secrets cannot be stored as memory."}
    except ValueError as exc:
        return {"ok": False, "error": f"Convention could not be stored: {exc}"}
    return {"ok": True, "revision": revision}


def gemini_agent_response(
    task: str,
    injected_memory: dict[str, Any],
    store: MemoryStore,
    session: str,
    client: GeminiClient,
    allow_memory_write: bool = False,
) -> str:
    """Run Gemini with injected memory and a controlled durable-memory write tool."""
    contents: list[dict[str, Any]] = [
        {"role": "user", "parts": [{"text": build_gemini_prompt(task, injected_memory)}]}
    ]
    for _ in range(MAX_GEMINI_TOOL_ROUNDS):
        response = client.generate(contents, tools=[REMEMBER_CONVENTION_TOOL])
        model_content = _gemini_candidate_content(response)
        function_calls = [
            part["functionCall"]
            for part in model_content["parts"]
            if isinstance(part, dict) and isinstance(part.get("functionCall"), dict)
        ]
        if not function_calls:
            answer = _gemini_text(model_content)
            if answer:
                return answer
            raise GeminiError("Gemini returned neither text nor a function call")

        contents.append(model_content)
        function_responses: list[dict[str, Any]] = []
        for call in function_calls:
            name = call.get("name")
            result = (
                _remember_result(store, session, call.get("args"), allow_memory_write)
                if name == "remember_convention"
                else {"ok": False, "error": "Unknown tool requested."}
            )
            function_response: dict[str, Any] = {"name": str(name), "response": result}
            if isinstance(call.get("id"), str) and call["id"]:
                function_response["id"] = call["id"]
            function_responses.append({"functionResponse": function_response})
        contents.append({"role": "user", "parts": function_responses})
    raise GeminiError("Gemini requested too many memory-write tool rounds")


def command_remember(args: argparse.Namespace) -> int:
    store = MemoryStore(args.store)
    revision = store.record(args.topic, args.value, args.session, args.at)
    print("SAVED_REVISION")
    print(json.dumps(revision, ensure_ascii=False, indent=2))
    _print_audit_warning(store)
    return 0


def command_ask(args: argparse.Namespace) -> int:
    store = MemoryStore(args.store)
    payload = (
        store.injected_memory()
        if args.all_active_memory
        else store.injected_memory(
            task=args.task, topics=args.memory_topic, limit=args.max_memory_items
        )
    )
    store.record_retrieval(args.session, payload)
    print(format_injected_memory(payload))
    print("AGENT_RESPONSE")
    if args.provider == "gemini":
        print(
            gemini_agent_response(
                args.task,
                payload,
                store,
                args.session,
                GeminiClient(model=args.gemini_model),
                allow_memory_write=args.allow_memory_write,
            )
        )
    else:
        print(agent_response(args.task, payload))
    _print_audit_warning(store)
    return 0


def command_history(args: argparse.Namespace) -> int:
    print(json.dumps(MemoryStore(args.store).load(), ensure_ascii=False, indent=2))
    return 0


def _print_audit_warning(store: MemoryStore) -> None:
    if store.last_audit_error:
        print(
            "WARNING: Memory state succeeded, but its audit record could not be written: "
            f"{store.last_audit_error}",
            file=sys.stderr,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Challenge A persistent-memory harness")
    commands = parser.add_subparsers(dest="command", required=True)

    remember = commands.add_parser("remember", help="record or update a project convention")
    remember.add_argument("--store", required=True, help="path to memory.json")
    remember.add_argument("--topic", required=True)
    remember.add_argument("--value", required=True)
    remember.add_argument("--session", required=True)
    remember.add_argument("--at", help="ISO timestamp; optional, useful for reproducible demos")
    remember.set_defaults(func=command_remember)

    ask = commands.add_parser("ask", help="open a session with injected active memory")
    ask.add_argument("--store", required=True, help="path to memory.json")
    ask.add_argument("--session", required=True, help="session id recorded in the injection audit")
    ask.add_argument("--task", required=True)
    ask.add_argument("--provider", choices=("offline", "gemini"), default="offline")
    ask.add_argument("--gemini-model", help="override GEMINI_MODEL for this Gemini request")
    ask.add_argument(
        "--allow-memory-write",
        action="store_true",
        help="allow Gemini to persist validated conventions for this explicitly approved ask",
    )
    retrieval = ask.add_mutually_exclusive_group()
    retrieval.add_argument(
        "--memory-topic", action="append", help="inject this topic (repeatable) instead of ranking"
    )
    retrieval.add_argument(
        "--all-active-memory", action="store_true", help="inject every active convention"
    )
    ask.add_argument(
        "--max-memory-items",
        type=_positive_int,
        default=3,
        help="maximum relevant conventions to inject (default: 3)",
    )
    ask.set_defaults(func=command_ask)

    history = commands.add_parser("history", help="show all revisions, including superseded ones")
    history.add_argument("--store", required=True, help="path to memory.json")
    history.set_defaults(func=command_history)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (ValueError, OSError, GeminiError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
