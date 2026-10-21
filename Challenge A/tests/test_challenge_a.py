from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import memory_harness
from memory_harness import MemoryStore, agent_response, format_injected_memory


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
