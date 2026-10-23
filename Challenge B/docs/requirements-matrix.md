# Requirement mapping

| Requirement from Challenge B | Implementation choice | Automated evidence / demo |
| --- | --- | --- |
| Compact a long session before context is full | Configurable token/message/repetition/milestone monitor | `test_context_reduction`, `test_monitor_supports_auto_and_manual_paths`, `demo:b1` |
| Preserve goal, constraint, findings, failure, files and next action | `Checkpoint` schema plus `evidence_ids` | `test_checkpoint_preserves_critical_information` |
| Resume without raw history | Rebuild three messages from checkpoint only; originals archive-only | `test_correct_continuation_uses_checkpoint`, `test_no_raw_context_reinjection` |
| Many reproducible logs and ground truth | Seeded generator, 60 files × 90 events default, manifest | `test_runtime_processes_multiple_files_and_correctly_aggregates`, `demo:b2` |
| Code Mode orchestrates reads inside runtime | `SafeLogRuntime.run_code` invokes list/read/aggregate internally | runtime trace: 61 internal calls, one visible final result |
| Do not inject raw logs | Findings schema and diagnostic counter set raw exposure to zero | `test_no_raw_log_leakage` |
| Compare native calling and Code Mode honestly | Same files and parser; native counts every raw read as model-visible | `test_native_baseline_exposes_more_context_than_code_mode`, evidence table |
| Runtime safety | Resolved-root allowlist, program allowlist, file/byte/time caps | `test_runtime_safety` |
| All three query types | Top errors, auth timing/files, refresh-race signals | `demo:b2`, `test_auth_and_race_queries_are_derived_from_aggregate` |
| Optional real LLM execution | Gemini REST adapter, `.env.example`, `--provider gemini` | Mock-provider prompt boundary and missing-key tests |

“Token estimate,” fixed thresholds and the offline deterministic policy are implementation choices. The functional requirements in the first column come directly from the assignment.
