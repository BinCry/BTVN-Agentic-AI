from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import memory_harness
from memory_harness import MemoryStore, agent_response, format_injected_memory


class FakeGeminiClient:
    """Record requests and replay deterministic Gemini API responses."""

    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = iter(responses)
        self.calls: list[dict[str, object]] = []

    def generate(
        self, contents: list[dict[str, object]], tools: list[dict[str, object]]
    ) -> dict[str, object]:
        self.calls.append({"contents": contents, "tools": tools})
        return next(self.responses)


class ChallengeATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = MemoryStore(Path(self.temp_dir.name) / "memory.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_new_session_receives_and_uses_prior_convention(self) -> None:
        self.store.record("api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z")

        # A fresh MemoryStore models a process/session started later.
        new_session_store = MemoryStore(self.store.path)
        injected = new_session_store.injected_memory()
        response = agent_response("Create a user endpoint", injected)

        self.assertEqual(injected["conventions"][0]["value"], "camelCase")
        self.assertIn("userId", response)
        self.assertIn("createdAt", response)

    def test_update_supersedes_old_revision_and_new_session_uses_new_one(self) -> None:
        self.store.record("api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z")
        self.store.record("api_field_style", "snake_case", "day-3", "2026-10-21T09:10:00Z")

        persisted = self.store.load()["conventions"]
        v1, v2 = persisted
        self.assertEqual((v1["status"], v1["superseded_by"]), ("superseded", 2))
        self.assertEqual((v2["status"], v2["version"]), ("active", 2))

        injected = MemoryStore(self.store.path).injected_memory()
        rendered_context = format_injected_memory(injected)
        response = agent_response("Create a user endpoint", injected)
        self.assertIn("snake_case", rendered_context)
        self.assertNotIn("camelCase", rendered_context)
        self.assertIn("user_id", response)
        self.assertIn("created_at", response)

    def test_printed_context_is_exact_retrieval_payload(self) -> None:
        self.store.record("api_field_style", "snake_case", "day-3", "2026-10-21T09:10:00Z")
        payload = self.store.injected_memory()
        printed = format_injected_memory(payload)
        raw_json = printed.split("--- INJECTED_MEMORY ---\n", 1)[1].split(
            "\n--- END_INJECTED_MEMORY ---", 1
        )[0]
        self.assertEqual(json.loads(raw_json), payload)

    def test_task_retrieval_selects_relevant_active_conventions(self) -> None:
        self.store.record("api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z")
        self.store.record(
            "database_migration_style", "PostgreSQL migrations", "day-1", "2026-10-21T09:01:00Z"
        )
        self.store.record(
            "authentication_scheme", "JWT bearer", "day-1", "2026-10-21T09:02:00Z"
        )

        payload = self.store.injected_memory(
            task="Create a PostgreSQL API endpoint protected by JWT", limit=3
        )
        self.assertEqual(
            {item["topic"] for item in payload["conventions"]},
            {"api_field_style", "database_migration_style", "authentication_scheme"},
        )
        self.assertEqual(
            self.store.injected_memory(task="Design a frontend page", limit=3)["conventions"], []
        )
        self.assertEqual(
            self.store.injected_memory(
                task="irrelevant", topics=["authentication_scheme"], limit=1
            )["conventions"][0]["value"],
            "JWT bearer",
        )

    def test_gemini_receives_the_exact_printed_injected_memory(self) -> None:
        self.store.record("api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z")
        payload = self.store.injected_memory(task="Create an API endpoint", limit=3)
        client = FakeGeminiClient(
            [{"candidates": [{"content": {"role": "model", "parts": [{"text": "Gemini answer"}]}}]}]
        )

        answer = memory_harness.gemini_agent_response(
            "Create an API endpoint", payload, self.store, "day-2", client  # type: ignore[arg-type]
        )

        self.assertEqual(answer, "Gemini answer")
        prompt = client.calls[0]["contents"][0]["parts"][0]["text"]
        self.assertIn(format_injected_memory(payload), prompt)

    def test_gemini_tool_call_persists_a_valid_convention_then_answers(self) -> None:
        client = FakeGeminiClient(
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "id": "call-1",
                                            "name": "remember_convention",
                                            "args": {
                                                "topic": "authentication_scheme",
                                                "value": "JWT bearer",
                                            },
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "Saved."}]}}]},
            ]
        )

        answer = memory_harness.gemini_agent_response(
            "From now on, use JWT bearer authentication.",
            self.store.injected_memory(),
            self.store,
            "day-1",
            client,  # type: ignore[arg-type]
            allow_memory_write=True,
        )

        self.assertEqual(answer, "Saved.")
        self.assertEqual(self.store.active_conventions()[0]["value"], "JWT bearer")
        second_request = client.calls[1]["contents"]
        self.assertEqual(second_request[1]["role"], "model")
        function_response = second_request[2]["parts"][0]["functionResponse"]
        self.assertEqual(function_response["id"], "call-1")
        self.assertTrue(function_response["response"]["ok"])

    def test_gemini_invalid_tool_call_cannot_persist_sensitive_memory(self) -> None:
        client = FakeGeminiClient(
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "remember_convention",
                                            "args": {
                                                "topic": "authentication_scheme",
                                                "value": "password=not-for-storage",
                                            },
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "Not saved."}]}}]},
            ]
        )

        memory_harness.gemini_agent_response(
            "Remember this key",
            self.store.injected_memory(),
            self.store,
            "day-1",
            client,  # type: ignore[arg-type]
            allow_memory_write=True,
        )

        self.assertEqual(self.store.active_conventions(), [])
        result = client.calls[1]["contents"][2]["parts"][0]["functionResponse"]["response"]
        self.assertFalse(result["ok"])

    def test_gemini_tool_call_needs_explicit_write_permission(self) -> None:
        client = FakeGeminiClient(
            [
                {
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "remember_convention",
                                            "args": {
                                                "topic": "personal_note",
                                                "value": "Alice prefers coffee",
                                            },
                                        }
                                    }
                                ],
                            }
                        }
                    ]
                },
                {"candidates": [{"content": {"role": "model", "parts": [{"text": "Not saved."}]}}]},
            ]
        )

        memory_harness.gemini_agent_response(
            "Alice prefers coffee", self.store.injected_memory(), self.store, "day-1", client  # type: ignore[arg-type]
        )

        self.assertEqual(self.store.active_conventions(), [])
        result = client.calls[1]["contents"][2]["parts"][0]["functionResponse"]["response"]
        self.assertFalse(result["ok"])
        self.assertIn("disabled", result["error"])

    def test_manual_remember_rejects_sensitive_value_before_audit_write(self) -> None:
        for value in ("password=not-for-storage", "ghp_" + "x" * 36):
            with self.assertRaisesRegex(ValueError, "Credentials"):
                self.store.record(
                    "authentication_scheme", value, "day-1", "2026-10-21T09:00:00Z"
                )
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.store.audit_path.exists())

    def test_gemini_client_uses_header_auth_without_putting_key_in_url(self) -> None:
        captured: dict[str, object] = {}

        def transport(request: object) -> bytes:
            captured["url"] = request.full_url  # type: ignore[attr-defined]
            captured["key"] = next(
                value
                for name, value in request.header_items()  # type: ignore[attr-defined]
                if name.casefold() == "x-goog-api-key"
            )
            return b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'

        response = memory_harness.GeminiClient(
            api_key="test-key", model="gemini-test", transport=transport  # type: ignore[arg-type]
        ).generate([{"role": "user", "parts": [{"text": "hello"}]}])

        self.assertIn("models/gemini-test:generateContent", captured["url"])
        self.assertNotIn("test-key", captured["url"])
        self.assertEqual(captured["key"], "test-key")
        self.assertIn("candidates", response)

    def test_gemini_client_requires_a_key_before_network_access(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            memory_harness, "load_local_gemini_environment"
        ):
            with self.assertRaisesRegex(memory_harness.GeminiError, "GEMINI_API_KEY"):
                memory_harness.GeminiClient()

    def test_cli_always_prints_injected_memory_before_response_and_audits_it(self) -> None:
        store_path = Path(self.temp_dir.name) / "memory.json"
        root = Path(__file__).resolve().parents[1]
        common = [sys.executable, str(root / "memory_harness.py")]
        subprocess.run(
            common + [
                "remember", "--store", str(store_path), "--topic", "api_field_style",
                "--value", "camelCase", "--session", "day-1",
            ],
            cwd=root, check=True, capture_output=True, text=True,
        )
        result = subprocess.run(
            common + [
                "ask", "--store", str(store_path), "--session", "day-2",
                "--task", "Create a user endpoint",
            ],
            cwd=root, check=True, capture_output=True, text=True,
        )
        self.assertLess(result.stdout.index("--- INJECTED_MEMORY ---"), result.stdout.index("AGENT_RESPONSE"))
        raw_json = result.stdout.split("--- INJECTED_MEMORY ---\n", 1)[1].split(
            "\n--- END_INJECTED_MEMORY ---", 1
        )[0]
        self.assertEqual(json.loads(raw_json), MemoryStore(store_path).injected_memory())
        audit = (store_path.parent / "memory-audit.jsonl").read_text(encoding="utf-8")
        self.assertIn('"event": "memory_injected"', audit)

    def test_similar_store_names_have_separate_mutex_and_audit_paths(self) -> None:
        first = MemoryStore(Path(self.temp_dir.name) / "memory.json")
        second = MemoryStore(Path(self.temp_dir.name) / "memory.json.lock")
        first.record("api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z")
        second.record("api_field_style", "snake_case", "day-1", "2026-10-21T09:00:00Z")
        first.record("api_field_style", "snake_case", "day-2", "2026-10-21T09:01:00Z")

        self.assertNotEqual(first._mutex_name(), second._mutex_name())
        self.assertNotEqual(first.audit_path, second.audit_path)
        self.assertEqual(first.active_conventions()[0]["value"], "snake_case")

    def test_writer_lock_blocks_competing_writer_then_releases(self) -> None:
        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_errors: list[Exception] = []

        def hold_lock() -> None:
            try:
                with MemoryStore(self.store.path)._write_lock():
                    holder_ready.set()
                    release_holder.wait(timeout=2)
            except Exception as exc:  # pragma: no cover - surfaced below
                holder_errors.append(exc)

        holder = threading.Thread(target=hold_lock)
        holder.start()
        self.assertTrue(holder_ready.wait(timeout=1), "holder did not acquire the lock")
        with patch.object(memory_harness, "LOCK_WAIT_MILLISECONDS", 50):
            with self.assertRaises(TimeoutError):
                self.store.record(
                    "api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z"
                )
        release_holder.set()
        holder.join(timeout=1)
        self.assertFalse(holder.is_alive())
        self.assertEqual(holder_errors, [])

        revision = self.store.record(
            "api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z"
        )
        self.assertEqual(revision["status"], "active")

    def test_malformed_schema_is_a_controlled_error(self) -> None:
        self.store.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "conventions": [
                        {
                            "topic": [],
                            "value": "camelCase",
                            "version": 1,
                            "status": "active",
                            "recorded_at": "2026-10-21T09:00:00Z",
                            "source_session": "day-1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ValueError, "Convention fields"):
            self.store.injected_memory()

    def test_non_object_or_non_string_status_is_a_controlled_error(self) -> None:
        self.store.path.write_text("[]", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Unsupported memory schema"):
            self.store.load()

        self.store.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "conventions": [
                        {
                            "topic": "api_field_style",
                            "value": "camelCase",
                            "version": 1,
                            "status": [],
                            "recorded_at": "2026-10-21T09:00:00Z",
                            "source_session": "day-1",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ValueError, "Unknown convention status"):
            self.store.load()

        self.store.path.write_text(
            json.dumps({"schema_version": True, "conventions": []}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Unsupported memory schema"):
            self.store.load()

        self.store.path.write_text(
            json.dumps({"schema_version": 1.0, "conventions": []}), encoding="utf-8"
        )
        with self.assertRaisesRegex(ValueError, "Unsupported memory schema"):
            self.store.load()

    def test_audit_failure_warns_but_does_not_hide_committed_memory(self) -> None:
        self.store.audit_path.mkdir()

        revision = self.store.record(
            "api_field_style", "camelCase", "day-1", "2026-10-21T09:00:00Z"
        )

        self.assertEqual(revision["value"], "camelCase")
        self.assertEqual(self.store.active_conventions()[0]["value"], "camelCase")
        self.assertIsNotNone(self.store.last_audit_error)

    def test_cli_path_error_is_clean_without_traceback(self) -> None:
        bad_store = Path(self.temp_dir.name) / "directory-not-file"
        bad_store.mkdir()
        root = Path(__file__).resolve().parents[1]

        result = subprocess.run(
            [
                sys.executable,
                str(root / "memory_harness.py"),
                "history",
                "--store",
                str(bad_store),
            ],
            cwd=root,
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Error:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

if __name__ == "__main__":
    unittest.main()
