# Challenge B — Context Management

An executable, dependency-free Python 3.11+ implementation of Challenge B. It proves two different context-engineering boundaries:

- **B1 — compaction:** long agent history becomes a structured, evidence-linked checkpoint before the agent resumes.
- **B2 — Code Mode:** a constrained runtime reads and aggregates many raw logs; the agent receives only compact structured findings.

It runs fully offline by default. `OfflineAgent` is deliberately a deterministic policy over actual checkpoint/findings data, not a claimed LLM call. Therefore provider token usage is unavailable in offline mode; all reported token values are clearly labeled estimates.

## Run

From this directory:

```powershell
python context_harness.py demo:b1 --output-dir demo-output
python context_harness.py demo:b2 --output-dir demo-output
python -m unittest discover -s tests -v
```

## Optional Gemini API key

No key is needed to submit or run the offline demos. To use Gemini later, copy `.env.example` to `.env`, set the key locally, then select the provider:

```powershell
Copy-Item .env.example .env
# Edit .env locally; never commit it.
python context_harness.py demo:b1 --provider gemini
python context_harness.py demo:b2 --provider gemini --gemini-model gemini-2.5-flash
```

`GEMINI_API_KEY` can instead be supplied as an environment variable. B1 sends only the reconstructed active context; B2 sends only the query and structured runtime findings. A missing key fails before any network request. The REST client uses Gemini `generateContent` directly through Python's standard library; provider token usage is not fabricated or estimated as real usage.

`demo:b1` writes `demo-output/b1-report.json`. `demo:b2` regenerates its seeded 60-file log dataset under `demo-output/logs/`, then writes `demo-output/b2-report.json`. Generated outputs are ignored by Git and can be deleted safely.

## What B1 demonstrates

The fixture starts the task “Fix refresh-token race condition without breaking existing API compatibility,” reads `auth.ts`, `session.ts`, and `auth.test.ts`, receives large test/search outputs, observes concurrent refresh failure, tries a larger TTL unsuccessfully, and prepares to inspect locking.

`ContextMonitor` supports a manual/milestone path and automatic thresholds. `SessionCompactor` applies KEEP/TRUNCATE/DROP and archives originals. Its checkpoint contains `goal`, `current_state`, `constraints`, `findings`, `failed_attempts`, `files`, `next_action`, and message IDs as evidence. Reconstruction uses only system instruction + checkpoint + continuation instruction, never archived raw logs.

## What B2 demonstrates

`generate_log_dataset()` creates timestamped INFO/WARN/ERROR logs from a fixed seed and emits `ground_truth.json`. `SafeLogRuntime.run_code("aggregate_logs_v1", query)` is a named allowlisted program, not arbitrary code/shell execution. It only reads `.log` files beneath its resolved root and enforces file count, total-byte, and wall-clock limits.

Within the runtime, `list_files` and `read_file` process every log; `LogAggregate` filters, groups, counts and references errors. The final payload contains findings and references only. Its trace records zero raw bytes delivered to the LLM boundary. The demo runs all three required query shapes: top errors, authentication timing/concentration, and refresh-race signals.

See [architecture.md](docs/architecture.md), [evidence.md](docs/evidence.md), and [requirements-matrix.md](docs/requirements-matrix.md).
