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
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if os.name == "nt":
    import ctypes
    from ctypes import wintypes
else:
    import fcntl


SCHEMA_VERSION = 1
LOCK_WAIT_MILLISECONDS = 5_000
AUTHORITATIVE_POLICY = (
    "Active conventions are authoritative. Superseded conventions are audit-only "
    "and must not be followed."
)


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

    def injected_memory(self) -> dict[str, Any]:
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
                for item in self.active_conventions()
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


def command_remember(args: argparse.Namespace) -> int:
    store = MemoryStore(args.store)
    revision = store.record(args.topic, args.value, args.session, args.at)
    print("SAVED_REVISION")
    print(json.dumps(revision, ensure_ascii=False, indent=2))
    _print_audit_warning(store)
    return 0


def command_ask(args: argparse.Namespace) -> int:
    store = MemoryStore(args.store)
    payload = store.injected_memory()
    store.record_retrieval(args.session, payload)
    print(format_injected_memory(payload))
    print("AGENT_RESPONSE")
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
    ask.set_defaults(func=command_ask)

    history = commands.add_parser("history", help="show all revisions, including superseded ones")
    history.add_argument("--store", required=True, help="path to memory.json")
    history.set_defaults(func=command_history)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Error: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
