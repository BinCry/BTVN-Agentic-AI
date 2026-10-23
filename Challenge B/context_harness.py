"""Executable offline harness for Challenge B: context management.

The module deliberately does not pretend to call an LLM.  ``OfflineAgent`` is
a small deterministic policy whose decisions are made from the compacted
checkpoint or the runtime's structured findings.  This makes the context
boundary and the assertions reproducible without an API key.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


TOKEN_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)
FILE_RE = re.compile(r"\b[\w.-]+\.(?:ts|log)\b")
EVENT_RE = re.compile(
    r"^(?P<time>\S+) \[(?P<service>[\w-]+)\] (?P<level>INFO|WARN|ERROR) (?P<body>.*)$"
)
CODE_RE = re.compile(r"\bcode=(?P<code>[A-Z][A-Z0-9_]+)\b")
ALLOWED_PROGRAMS = {"aggregate_logs_v1"}
DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def token_estimate(value: str) -> int:
    """Transparent offline token estimate: regex tokens, not provider usage."""
    return len(TOKEN_RE.findall(value))


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)


class GeminiError(RuntimeError):
    """Safe, user-facing failure for the optional Gemini provider."""


def load_local_gemini_environment(path: Path | None = None) -> None:
    """Load only Gemini settings from a local .env without executing its contents."""
    env_path = path or Path(__file__).resolve().with_name(".env")
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key not in {"GEMINI_API_KEY", "GEMINI_MODEL"} or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value:
            os.environ[key] = value


def _gemini_transport(request: Request) -> bytes:
    with urlopen(request, timeout=30) as response:
        return response.read()


class GeminiClient:
    """Small REST client; the injectable transport enables tests without a key/network."""

    def __init__(
        self, api_key: str | None = None, model: str | None = None,
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

    def generate_text(self, prompt: str) -> str:
        model = self.model.removeprefix("models/")
        request = Request(
            GEMINI_API_URL.format(model=quote(model, safe="-._")),
            data=json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}]}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key}, method="POST",
        )
        try:
            response = json.loads(self.transport(request).decode("utf-8"))
        except HTTPError as exc:
            raise GeminiError(f"Gemini API request failed ({exc.code})") from exc
        except URLError as exc:
            raise GeminiError(f"Could not reach Gemini API: {exc.reason}") from exc
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GeminiError("Gemini API returned an unreadable response") from exc
        candidates = response.get("candidates") if isinstance(response, dict) else None
        if not isinstance(candidates, list) or not candidates or not isinstance(candidates[0], dict):
            raise GeminiError("Gemini returned no candidates")
        content = candidates[0].get("content")
        parts = content.get("parts") if isinstance(content, dict) else None
        text = "".join(part.get("text", "") for part in parts if isinstance(part, dict)) if isinstance(parts, list) else ""
        if not text.strip():
            raise GeminiError("Gemini returned no text")
        return text.strip()


def build_gemini_b1_prompt(active_context: list["Message"]) -> str:
    """The only B1 payload allowed across the provider boundary."""
    payload = [{"role": item.role, "kind": item.kind, "content": item.content} for item in active_context]
    return (
        "You are continuing a technical debugging task. Use only the reconstructed active context below. "
        "Keep stated constraints, distinguish verified findings from hypotheses, and propose the next action. "
        "Do not ask for or assume archived tool output.\n\n"
        f"RECONSTRUCTED_ACTIVE_CONTEXT:\n{json_text(payload)}"
    )


def build_gemini_b2_prompt(query: str, findings: dict[str, Any]) -> str:
    """The only B2 payload allowed across the provider boundary: no raw log data."""
    return (
        "Answer the user's log-analysis question using only the structured runtime findings below. "
        "State observed evidence separately from root-cause inference.\n\n"
        f"QUESTION:\n{query}\n\nSTRUCTURED_FINDINGS:\n{json_text(findings)}"
    )


@dataclass
class Message:
    role: str
    kind: str
    content: str
    id: str


@dataclass
class ContextMetrics:
    messages: int
    characters: int
    token_estimate: int
    tool_output_messages: int


def measure_context(messages: Iterable[Message]) -> ContextMetrics:
    values = list(messages)
    text = "\n".join(message.content for message in values)
    return ContextMetrics(
        messages=len(values),
        characters=len(text),
        token_estimate=token_estimate(text),
        tool_output_messages=sum(message.kind == "tool" for message in values),
    )


@dataclass
class Checkpoint:
    goal: str
    current_state: str
    constraints: list[str]
    findings: list[str]
    failed_attempts: list[str]
    files: list[str]
    next_action: str
    evidence_ids: dict[str, list[str]]
    created_from_messages: int


@dataclass
class CompactionResult:
    checkpoint: Checkpoint
    before: ContextMetrics
    after: ContextMetrics
    active_context: list[Message]
    archive: list[Message]
    trigger: str
    operations: dict[str, int]


class ContextMonitor:
    def __init__(self, token_threshold: int = 1_100, message_threshold: int = 12) -> None:
        self.token_threshold = token_threshold
        self.message_threshold = message_threshold

    def should_compact(self, messages: list[Message], milestone: bool = False) -> str | None:
        metrics = measure_context(messages)
        tool_texts = [item.content for item in messages if item.kind == "tool"]
        repeated = len(tool_texts) != len(set(tool_texts))
        if milestone:
            return "milestone"
        if metrics.token_estimate >= self.token_threshold:
            return "token-threshold"
        if metrics.messages >= self.message_threshold or repeated:
            return "history-growth"
        return None


class SessionCompactor:
    """Create a structured checkpoint from observed session messages.

    The extraction rules are intentionally conservative: a hypothesis remains
    wording from the message, while only explicit test/tool observations become
    findings.  The complete originals remain in ``archive`` and are never used
    by reconstruction.
    """

    def build_checkpoint(self, messages: list[Message]) -> Checkpoint:
        ids: dict[str, list[str]] = defaultdict(list)
        goal = ""
        current_state = ""
        constraints: list[str] = []
        findings: list[str] = []
        failed: list[str] = []
        files: set[str] = set()
        next_action = ""

        for message in messages:
            text = message.content.strip()
            lower = text.lower()
            # Relevant files are tools the agent explicitly opened (or the
            # filename header of that tool result), not incidental filenames
            # embedded in a stack trace.
            if message.kind == "tool-call":
                files.update(FILE_RE.findall(text))
            elif message.kind == "tool":
                first_line = text.splitlines()[0] if text else ""
                files.update(FILE_RE.findall(first_line))
            if message.role == "user" and lower.startswith("goal:"):
                goal = text.split(":", 1)[1].strip()
                ids["goal"].append(message.id)
            if ("backward compatible" in lower or "api compatibility" in lower) and not (
                message.role == "user" and lower.startswith("goal:")
            ):
                line = next((line.strip() for line in text.splitlines() if "compatible" in line.lower()), text)
                if line not in constraints:
                    constraints.append(line)
                    ids["constraints"].append(message.id)
            if "handler implemented" in lower and "test failing" in lower:
                current_state = "handler implemented; concurrent-refresh test still failing"
                ids["current_state"].append(message.id)
            if "concurrent refresh" in lower and ("fail" in lower or "race" in lower):
                finding = "Verified failure occurs during concurrent refresh."
                if finding not in findings:
                    findings.append(finding)
                    ids["findings"].append(message.id)
            if "increase" in lower and "ttl" in lower and ("did not" in lower or "still" in lower):
                attempt = "Increasing token TTL did not resolve the concurrent-refresh failure."
                if attempt not in failed:
                    failed.append(attempt)
                    ids["failed_attempts"].append(message.id)
            if "next_action:" in lower:
                next_action = text.split(":", 1)[1].strip()
                ids["next_action"].append(message.id)

        if not all([goal, current_state, constraints, findings, failed, files, next_action]):
            missing = [
                name for name, value in {
                    "goal": goal, "current_state": current_state, "constraints": constraints,
                    "findings": findings, "failed_attempts": failed, "files": files,
                    "next_action": next_action,
                }.items() if not value
            ]
            raise ValueError(f"Cannot compact: required checkpoint evidence is missing: {', '.join(missing)}")
        return Checkpoint(
            goal=goal,
            current_state=current_state,
            constraints=constraints,
            findings=findings,
            failed_attempts=failed,
            files=sorted(files),
            next_action=next_action,
            evidence_ids={key: sorted(set(value)) for key, value in ids.items()},
            created_from_messages=len(messages),
        )

    def compact(self, messages: list[Message], trigger: str) -> CompactionResult:
        before = measure_context(messages)
        checkpoint = self.build_checkpoint(messages)
        checkpoint_message = Message("system", "checkpoint", json_text(asdict(checkpoint)), "checkpoint-1")
        active = [
            Message("system", "instruction", "Continue the technical task from the checkpoint. Preserve constraints.", "system-1"),
            checkpoint_message,
            Message("assistant", "continuation", "Resume from the checkpoint; do not reload archived raw tool output.", "resume-1"),
        ]
        after = measure_context(active)
        return CompactionResult(
            checkpoint=checkpoint, before=before, after=after, active_context=active,
            archive=list(messages), trigger=trigger,
            operations={"keep": 7, "truncate": sum(item.kind == "tool" for item in messages), "drop": len(messages) - 3},
        )


class OfflineAgent:
    """A verifiable offline continuation policy; no LLM/API is claimed."""

    def continue_debugging(self, active_context: list[Message]) -> dict[str, Any]:
        checkpoint_message = next((item for item in active_context if item.kind == "checkpoint"), None)
        if checkpoint_message is None:
            raise ValueError("No compacted checkpoint in active context")
        data = json.loads(checkpoint_message.content)
        next_action = data["next_action"].lower()
        if "locking" not in next_action or not any("TTL" in item for item in data["failed_attempts"]):
            raise ValueError("Checkpoint does not support a safe continuation")
        if not any("backward compatible" in item.lower() for item in data["constraints"]):
            raise ValueError("Compatibility constraint was lost")
        return {
            "action": "Inspect locking or single-flight coordination around the refresh handler.",
            "reason": "The verified failure is concurrent refresh; TTL was already tried and failed.",
            "guardrail": "Keep the existing refresh-token API backward compatible.",
            "used_checkpoint_fields": ["findings", "failed_attempts", "constraints", "next_action", "files"],
        }

    def answer_findings(self, query: str, findings: dict[str, Any]) -> str:
        query_key = classify_query(query)
        if query_key == "top_errors":
            rows = findings["top_errors"][:3]
            return "Top errors: " + "; ".join(
                f"{row['code']}={row['count']} ({', '.join(row['files'][:3])})" for row in rows
            ) + "."
        if query_key == "auth_summary":
            auth = findings["authentication"]
            return (
                f"Authentication errors: {auth['count']}; first observed {auth['first_timestamp']}; "
                f"concentrated in {', '.join(auth['files'][:5])}."
            )
        race = findings["refresh_race"]
        return (
            f"Observed {race['count']} REFRESH_TOKEN_RACE events in {race['file_count']} files. "
            f"Evidence: {race['signals'][0] if race['signals'] else 'none'}. "
            "This is evidence of a concurrency symptom, not proof of a root cause."
        )


def build_auth_debug_session() -> list[Message]:
    """Build a long, consistent session with real raw-like outputs for B1."""
    messages = [
        Message("system", "instruction", "Act as a debugging agent. Record verified facts separately from hypotheses.", "m01"),
        Message("user", "request", "Goal: Fix refresh-token race condition without breaking existing API compatibility.", "m02"),
        Message("assistant", "analysis", "Constraint acknowledged: keep the refresh endpoint backward compatible for current clients.", "m03"),
        Message("assistant", "tool-call", "read_file auth.ts", "m04"),
        Message("tool", "tool", "auth.ts\n" + "export async function refreshToken() { /* 180 lines omitted in UI */ }\n" * 18, "m05"),
        Message("assistant", "tool-call", "read_file session.ts", "m06"),
        Message("tool", "tool", "session.ts\n" + "session rotation and token lookup\n" * 24, "m07"),
        Message("assistant", "tool-call", "read_file auth.test.ts", "m08"),
        Message("tool", "tool", "auth.test.ts\nhandler implemented; test failing: concurrent refresh returns two rotations.\n" + "assert refresh behavior\n" * 22, "m09"),
        Message("tool", "tool", "TEST LOG\nERROR concurrent refresh assertion failed: expected exactly one token rotation\nSTACK_TRACE\n" + " at refresh.spec.ts:42\n" * 35, "m10"),
        Message("assistant", "analysis", "Attempt: increase refresh token TTL before changing synchronization.", "m11"),
        Message("tool", "tool", "TEST LOG after TTL increase: concurrent refresh still fails; two requests both rotate token.\n" + "repeated test output\n" * 34, "m12"),
        Message("tool", "tool", "SEARCH OUTPUT\n" + "refreshToken reference in auth.ts and session.ts\n" * 40, "m13"),
        Message("assistant", "analysis", "NEXT_ACTION: Inspect locking around the refresh handler and preserve the existing API response shape.", "m14"),
    ]
    return messages


def demo_b1(provider: str = "offline", gemini_model: str | None = None) -> dict[str, Any]:
    history = build_auth_debug_session()
    monitor = ContextMonitor(token_threshold=900, message_threshold=50)
    trigger = monitor.should_compact(history)
    if trigger is None:
        raise RuntimeError("B1 fixture did not reach a compaction trigger")
    result = SessionCompactor().compact(history, trigger)
    if provider == "gemini":
        continuation: dict[str, Any] | str = GeminiClient(model=gemini_model).generate_text(
            build_gemini_b1_prompt(result.active_context)
        )
    else:
        continuation = OfflineAgent().continue_debugging(result.active_context)
    return {
        "trigger": result.trigger,
        "before": asdict(result.before), "after": asdict(result.after),
        "reduction_percent": round((1 - result.after.token_estimate / result.before.token_estimate) * 100, 2),
        "provider": provider, "checkpoint": asdict(result.checkpoint), "continuation": continuation,
        "archive_messages": len(result.archive), "operations": result.operations,
    }


ERROR_WEIGHTS = [
    ("INFO", None, 42), ("WARN", None, 18), ("ERROR", "DB_TIMEOUT", 16),
    ("ERROR", "AUTH_INVALID_CREDENTIALS", 11), ("ERROR", "REFRESH_TOKEN_RACE", 8),
    ("ERROR", "UPSTREAM_503", 5),
]


def generate_log_dataset(root: Path, *, seed: int = 20261023, file_count: int = 60, entries_per_file: int = 90) -> dict[str, Any]:
    """Generate reproducible logs and a manifest computed while writing them."""
    root.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    choices = [item[:2] for item in ERROR_WEIGHTS]
    weights = [item[2] for item in ERROR_WEIGHTS]
    counters: Counter[str] = Counter()
    first_seen: dict[str, str] = {}
    last_seen: dict[str, str] = {}
    references: dict[str, list[str]] = defaultdict(list)
    services = ["auth-api", "session-api", "orders-api", "worker"]
    start = datetime(2026, 10, 23, 8, 0, tzinfo=UTC)
    total_entries = 0
    for index in range(file_count):
        service = services[index % len(services)]
        relative = f"{service}-{index:03d}.log"
        path = root / relative
        lines: list[str] = []
        for row in range(entries_per_file):
            timestamp = start + timedelta(seconds=(index * entries_per_file + row) * 7)
            level, code = rng.choices(choices, weights=weights, k=1)[0]
            stamp = timestamp.isoformat().replace("+00:00", "Z")
            if level == "INFO":
                body = f"request completed request_id=req-{index:03d}-{row:03d}"
            elif level == "WARN":
                body = f"retry scheduled queue=refresh request_id=req-{index:03d}-{row:03d}"
            elif code == "DB_TIMEOUT":
                body = f"code={code} database query exceeded 1200ms request_id=req-{index:03d}-{row:03d}"
            elif code == "AUTH_INVALID_CREDENTIALS":
                body = f"code={code} authentication rejected request_id=req-{index:03d}-{row:03d}"
            elif code == "REFRESH_TOKEN_RACE":
                body = f"code={code} concurrent refresh observed stale token version request_id=req-{index:03d}-{row:03d}"
            else:
                body = f"code={code} upstream identity provider unavailable request_id=req-{index:03d}-{row:03d}"
            lines.append(f"{stamp} [{service}] {level} {body}\n")
            total_entries += 1
            if code:
                counters[code] += 1
                first_seen.setdefault(code, stamp)
                last_seen[code] = stamp
                references[code].append(f"{relative}:{len(lines)}")
                if code in {"DB_TIMEOUT", "REFRESH_TOKEN_RACE"}:
                    lines.append("  at Runtime.handle (runtime.ts:81)\n")
                    lines.append("  at processTicksAndRejections (node:internal/process/task_queues:95:5)\n")
        path.write_text("".join(lines), encoding="utf-8")
    manifest = {
        "seed": seed, "file_count": file_count, "total_entries": total_entries,
        "error_counts": dict(sorted(counters.items())),
        "first_seen": first_seen, "last_seen": last_seen,
        "references": {key: value[:10] for key, value in references.items()},
    }
    (root / "ground_truth.json").write_text(json_text(manifest) + "\n", encoding="utf-8")
    return manifest


class RuntimeSafetyError(RuntimeError):
    pass


class SafeLogRuntime:
    """A constrained program runtime. Raw reads exist only while this runs."""

    def __init__(self, root: Path, *, max_files: int = 200, max_total_bytes: int = 8_000_000, timeout_seconds: float = 5.0) -> None:
        self.root = root.resolve()
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self.timeout_seconds = timeout_seconds
        self.trace: dict[str, Any] = {"tool_calls": 0, "raw_bytes_processed": 0, "raw_results_delivered_to_llm": 0, "files": []}

    def _check_time(self, started: float) -> None:
        if time.monotonic() - started > self.timeout_seconds:
            raise TimeoutError("runtime execution exceeded configured timeout")

    def _resolve(self, relative: str) -> Path:
        candidate = (self.root / relative).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise RuntimeSafetyError("file access is outside the allowed log directory") from exc
        return candidate

    def list_files(self) -> list[str]:
        files = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*.log") if path.is_file())
        if len(files) > self.max_files:
            raise RuntimeSafetyError("file count exceeds runtime allowlist limit")
        self.trace["tool_calls"] += 1
        return files

    def read_file(self, relative: str) -> str:
        path = self._resolve(relative)
        if not path.is_file():
            raise FileNotFoundError(f"allowed log file does not exist: {relative}")
        # Bounded read prevents a file growing between a size check and read
        # from bypassing the aggregate byte budget.
        remaining = self.max_total_bytes - self.trace["raw_bytes_processed"]
        with path.open("rb") as log_file:
            raw_bytes = log_file.read(remaining + 1)
        if len(raw_bytes) > remaining:
            raise RuntimeSafetyError("raw log byte limit exceeded")
        data = raw_bytes.decode("utf-8")
        encoded_size = len(raw_bytes)
        self.trace["tool_calls"] += 1
        self.trace["raw_bytes_processed"] += encoded_size
        self.trace["files"].append(relative)
        return data

    def run_code(self, program: str, query: str) -> dict[str, Any]:
        if program not in ALLOWED_PROGRAMS:
            raise RuntimeSafetyError("program is not in the runtime allowlist")
        started = time.monotonic()
        aggregate = LogAggregate()
        for relative in self.list_files():
            self._check_time(started)
            aggregate.consume(relative, self.read_file(relative))
        self._check_time(started)
        findings = aggregate.findings(query)
        findings["runtime"] = {
            "program": program, "files_processed": len(self.trace["files"]),
            "tool_calls_inside_runtime": self.trace["tool_calls"],
            "raw_log_bytes_exposed_to_llm": 0,
            "token_estimate_of_final_findings": token_estimate(json.dumps(findings, ensure_ascii=False)),
        }
        return findings


class LogAggregate:
    def __init__(self) -> None:
        self.entries = 0
        self.error_counts: Counter[str] = Counter()
        self.files: dict[str, set[str]] = defaultdict(set)
        self.file_counts: dict[str, Counter[str]] = defaultdict(Counter)
        self.first: dict[str, str] = {}
        self.last: dict[str, str] = {}
        self.references: dict[str, list[str]] = defaultdict(list)

    def consume(self, filename: str, raw: str) -> None:
        for line_number, line in enumerate(raw.splitlines(), 1):
            event = EVENT_RE.match(line)
            if event is None:
                continue
            self.entries += 1
            code_match = CODE_RE.search(event.group("body"))
            if event.group("level") != "ERROR" or code_match is None:
                continue
            code = code_match.group("code")
            stamp = event.group("time")
            self.error_counts[code] += 1
            self.files[code].add(filename)
            self.file_counts[code][filename] += 1
            self.first.setdefault(code, stamp)
            self.last[code] = stamp
            if len(self.references[code]) < 12:
                self.references[code].append(f"{filename}:{line_number}")

    def findings(self, query: str) -> dict[str, Any]:
        def top_files(code: str) -> list[str]:
            return [name for name, _count in self.file_counts[code].most_common(8)]

        top = [
            {
                "code": code, "count": count, "file_count": len(self.files[code]),
                "files": top_files(code), "references": self.references[code][:5],
            }
            for code, count in self.error_counts.most_common()
        ]
        auth_codes = [code for code in self.error_counts if code.startswith("AUTH_")]
        auth_files = {name for code in auth_codes for name in self.files[code]}
        ranked_auth_files = [
            name for name, _count in sum((self.file_counts[code] for code in auth_codes), Counter()).most_common(8)
        ]
        auth_count = sum(self.error_counts[code] for code in auth_codes)
        race_count = self.error_counts["REFRESH_TOKEN_RACE"]
        return {
            "query_type": classify_query(query), "total_entries": self.entries,
            "error_counts": dict(sorted(self.error_counts.items())), "top_errors": top,
            "time_range": {"first": min(self.first.values(), default=None), "last": max(self.last.values(), default=None)},
            "authentication": {
                "count": auth_count, "first_timestamp": min((self.first[key] for key in auth_codes), default=None),
                "file_count": len(auth_files), "files": ranked_auth_files,
                "references": [ref for key in auth_codes for ref in self.references[key]][:8],
            },
            "refresh_race": {
                "count": race_count, "file_count": len(self.files["REFRESH_TOKEN_RACE"]),
                "files": top_files("REFRESH_TOKEN_RACE"),
                "references": self.references["REFRESH_TOKEN_RACE"][:8],
                "signals": (["REFRESH_TOKEN_RACE events explicitly report concurrent refresh and stale token version."] if race_count else []),
            },
        }


def classify_query(query: str) -> str:
    lowered = query.lower()
    if ("3" in lowered and "loại lỗi" in lowered) or "top" in lowered:
        return "top_errors"
    if "authentication" in lowered or "xác thực" in lowered:
        return "auth_summary"
    return "refresh_race"


def native_calling_baseline(root: Path, query: str) -> dict[str, Any]:
    """Simulate native tool calling: every raw read becomes model-visible context."""
    runtime = SafeLogRuntime(root)
    aggregate = LogAggregate()
    raw_bytes = 0
    calls = 0
    for relative in runtime.list_files():
        raw = runtime.read_file(relative)
        raw_bytes += len(raw.encode("utf-8"))
        calls += 1
        aggregate.consume(relative, raw)
    findings = aggregate.findings(query)
    return {
        "files_processed": calls, "tool_calls": calls + 1, "raw_log_bytes_exposed_to_llm": raw_bytes,
        "input_token_estimate": (raw_bytes + 3) // 4,  # bytes/4 is explicitly an estimate
        "accuracy_source": findings,
    }


def demo_b2(output_dir: Path, provider: str = "offline", gemini_model: str | None = None) -> dict[str, Any]:
    log_root = output_dir / "logs"
    if log_root.exists():
        shutil.rmtree(log_root)
    truth = generate_log_dataset(log_root)
    questions = [
        "Phân tích tất cả log files và cho biết 3 loại lỗi xuất hiện nhiều nhất, số lần xuất hiện và những file liên quan.",
        "Lỗi authentication xuất hiện bao nhiêu lần, bắt đầu từ khi nào và tập trung ở những file nào?",
        "Phân tích các log để xác định những dấu hiệu có liên quan đến refresh-token race condition.",
    ]
    results: list[dict[str, Any]] = []
    gemini = GeminiClient(model=gemini_model) if provider == "gemini" else None
    for query in questions:
        runtime = SafeLogRuntime(log_root)
        findings = runtime.run_code("aggregate_logs_v1", query)
        answer = (
            gemini.generate_text(build_gemini_b2_prompt(query, findings))
            if gemini else OfflineAgent().answer_findings(query, findings)
        )
        results.append({"question": query, "findings": findings, "answer": answer, "runtime_trace": runtime.trace})
    primary = results[0]
    findings = primary["findings"]
    baseline = native_calling_baseline(log_root, questions[0])
    comparison = {
        "files_processed": findings["runtime"]["files_processed"],
        "lines_or_entries_processed": findings["total_entries"],
        "native": {key: baseline[key] for key in ("tool_calls", "raw_log_bytes_exposed_to_llm", "input_token_estimate")},
        "code_mode": {
            "tool_calls_visible_to_llm": 1, "raw_log_bytes_exposed_to_llm": 0,
            "input_token_estimate": findings["runtime"]["token_estimate_of_final_findings"],
        },
        "accuracy_matches_ground_truth": findings["error_counts"] == truth["error_counts"],
        "estimate_note": "Token values are offline estimates; no provider API/token usage was invoked.",
    }
    return {"provider": provider, "ground_truth": truth, "queries": results, "comparison": comparison}


def write_demo(name: str, payload: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}-report.json"
    path.write_text(json_text(payload) + "\n", encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    # Windows shells may default to a legacy code page. The fixtures and CLI
    # intentionally include Vietnamese demo questions, so make output portable.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Challenge B offline context-management harness")
    parser.add_argument("command", choices=["demo:b1", "demo:b2", "generate-data"])
    parser.add_argument("--output-dir", type=Path, default=Path("demo-output"))
    parser.add_argument("--provider", choices=("offline", "gemini"), default="offline")
    parser.add_argument("--gemini-model", help="override GEMINI_MODEL for this request")
    args = parser.parse_args(argv)
    try:
        if args.command == "demo:b1":
            payload = demo_b1(args.provider, args.gemini_model)
            path = write_demo("b1", payload, args.output_dir)
        elif args.command == "demo:b2":
            payload = demo_b2(args.output_dir, args.provider, args.gemini_model)
            path = write_demo("b2", payload, args.output_dir)
        else:
            payload = generate_log_dataset(args.output_dir / "logs")
            path = args.output_dir / "logs" / "ground_truth.json"
    except GeminiError as exc:
        parser.exit(2, f"Error: {exc}\n")
    print(json_text(payload))
    print(f"\nReport written to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
