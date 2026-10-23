from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from context_harness import (  # noqa: E402
    ContextMonitor,
    GeminiClient,
    GeminiError,
    OfflineAgent,
    RuntimeSafetyError,
    SafeLogRuntime,
    SessionCompactor,
    build_auth_debug_session,
    build_gemini_b1_prompt,
    build_gemini_b2_prompt,
    generate_log_dataset,
    native_calling_baseline,
)


class SessionCompactionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.history = build_auth_debug_session()
        self.result = SessionCompactor().compact(self.history, trigger="manual")

    def test_context_reduction(self) -> None:
        self.assertLess(self.result.after.messages, self.result.before.messages)
        self.assertLess(self.result.after.token_estimate, self.result.before.token_estimate)
        self.assertGreater(
            1 - self.result.after.token_estimate / self.result.before.token_estimate, 0.50
        )

    def test_checkpoint_preserves_critical_information(self) -> None:
        checkpoint = self.result.checkpoint
        self.assertEqual(checkpoint.goal, "Fix refresh-token race condition without breaking existing API compatibility.")
        self.assertTrue(any("backward compatible" in item.lower() for item in checkpoint.constraints))
        self.assertIn("Verified failure occurs during concurrent refresh.", checkpoint.findings)
        self.assertTrue(any("TTL" in item for item in checkpoint.failed_attempts))
        self.assertEqual(checkpoint.files, ["auth.test.ts", "auth.ts", "session.ts"])
        self.assertIn("locking", checkpoint.next_action.lower())
        self.assertTrue(checkpoint.evidence_ids["goal"])

    def test_correct_continuation_uses_checkpoint(self) -> None:
        continued = OfflineAgent().continue_debugging(self.result.active_context)
        self.assertIn("locking", continued["action"].lower())
        self.assertNotIn("increase", continued["action"].lower())
        self.assertIn("backward compatible", continued["guardrail"].lower())

    def test_no_raw_context_reinjection(self) -> None:
        reconstructed = "\n".join(item.content for item in self.result.active_context)
        archived = "\n".join(item.content for item in self.result.archive)
        self.assertIn("STACK_TRACE", archived)
        self.assertNotIn("STACK_TRACE", reconstructed)
        self.assertNotIn("repeated test output", reconstructed)
        self.assertLess(len(reconstructed), len(archived))

    def test_monitor_supports_auto_and_manual_paths(self) -> None:
        self.assertIsNotNone(ContextMonitor(token_threshold=1).should_compact(self.history))
        self.assertEqual(ContextMonitor(99_999, 99_999).should_compact(self.history, milestone=True), "milestone")


class CodeModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "logs"
        self.truth = generate_log_dataset(self.root, file_count=16, entries_per_file=50)
        self.query = "Phân tích tất cả log files và cho biết 3 loại lỗi xuất hiện nhiều nhất, số lần xuất hiện và những file liên quan."

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runtime_processes_multiple_files_and_correctly_aggregates(self) -> None:
        runtime = SafeLogRuntime(self.root)
        findings = runtime.run_code("aggregate_logs_v1", self.query)
        self.assertEqual(findings["runtime"]["files_processed"], self.truth["file_count"])
        self.assertGreater(findings["runtime"]["files_processed"], 1)
        self.assertEqual(findings["total_entries"], self.truth["total_entries"])
        self.assertEqual(findings["error_counts"], self.truth["error_counts"])
        self.assertEqual(findings["top_errors"][0]["code"], max(self.truth["error_counts"], key=self.truth["error_counts"].get))

    def test_no_raw_log_leakage(self) -> None:
        runtime = SafeLogRuntime(self.root)
        findings = runtime.run_code("aggregate_logs_v1", self.query)
        final_payload = json.dumps(findings)
        one_raw_line = (self.root / runtime.trace["files"][0]).read_text(encoding="utf-8").splitlines()[0]
        self.assertNotIn(one_raw_line, final_payload)
        self.assertEqual(runtime.trace["raw_results_delivered_to_llm"], 0)
        self.assertEqual(findings["runtime"]["raw_log_bytes_exposed_to_llm"], 0)

    def test_native_baseline_exposes_more_context_than_code_mode(self) -> None:
        runtime = SafeLogRuntime(self.root)
        findings = runtime.run_code("aggregate_logs_v1", self.query)
        native = native_calling_baseline(self.root, self.query)
        self.assertGreater(native["raw_log_bytes_exposed_to_llm"], 0)
        self.assertGreater(native["input_token_estimate"], findings["runtime"]["token_estimate_of_final_findings"])
        self.assertEqual(native["accuracy_source"]["error_counts"], findings["error_counts"])

    def test_runtime_safety(self) -> None:
        runtime = SafeLogRuntime(self.root)
        with self.assertRaises(FileNotFoundError):
            runtime.read_file("not-here.log")
        with self.assertRaises(RuntimeSafetyError):
            runtime.read_file("../outside.log")
        with self.assertRaises(RuntimeSafetyError):
            runtime.run_code("shell rm -rf", self.query)
        with self.assertRaises(RuntimeSafetyError):
            SafeLogRuntime(self.root, max_total_bytes=10).read_file("auth-api-000.log")
        with self.assertRaises(TimeoutError):
            SafeLogRuntime(self.root, timeout_seconds=0).run_code("aggregate_logs_v1", self.query)

    def test_auth_and_race_queries_are_derived_from_aggregate(self) -> None:
        runtime = SafeLogRuntime(self.root)
        auth = runtime.run_code("aggregate_logs_v1", "Authentication errors from when?")
        race = SafeLogRuntime(self.root).run_code("aggregate_logs_v1", "Find refresh-token race condition signals")
        self.assertEqual(auth["authentication"]["count"], self.truth["error_counts"].get("AUTH_INVALID_CREDENTIALS", 0))
        self.assertEqual(race["refresh_race"]["count"], self.truth["error_counts"].get("REFRESH_TOKEN_RACE", 0))
        self.assertTrue(race["refresh_race"]["signals"])


class GeminiProviderTests(unittest.TestCase):
    def test_client_uses_header_and_returns_mocked_text(self) -> None:
        captured = {}

        def transport(request):
            captured["key"] = request.get_header("X-goog-api-key")
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return b'{"candidates":[{"content":{"parts":[{"text":"Model response"}]}}]}'

        response = GeminiClient(api_key="test-key-not-a-real-secret", model="models/gemini-test", transport=transport).generate_text("safe prompt")
        self.assertEqual(response, "Model response")
        self.assertEqual(captured["key"], "test-key-not-a-real-secret")
        self.assertEqual(captured["payload"]["contents"][0]["parts"][0]["text"], "safe prompt")

    def test_missing_key_stops_before_network(self) -> None:
        with patch("context_harness.load_local_gemini_environment"):
            with patch.dict("context_harness.os.environ", {}, clear=True):
                with self.assertRaisesRegex(GeminiError, "GEMINI_API_KEY"):
                    GeminiClient()

    def test_provider_prompts_keep_raw_data_outside_boundary(self) -> None:
        result = SessionCompactor().compact(build_auth_debug_session(), trigger="manual")
        b1_prompt = build_gemini_b1_prompt(result.active_context)
        self.assertIn("RECONSTRUCTED_ACTIVE_CONTEXT", b1_prompt)
        self.assertIn("refresh-token race condition", b1_prompt)
        self.assertNotIn("STACK_TRACE", b1_prompt)
        self.assertNotIn("repeated test output", b1_prompt)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "logs"
            generate_log_dataset(root, file_count=3, entries_per_file=8)
            runtime = SafeLogRuntime(root)
            findings = runtime.run_code("aggregate_logs_v1", "top errors")
            b2_prompt = build_gemini_b2_prompt("top errors", findings)
            raw_line = (root / runtime.trace["files"][0]).read_text(encoding="utf-8").splitlines()[0]
            self.assertIn("STRUCTURED_FINDINGS", b2_prompt)
            self.assertNotIn(raw_line, b2_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
