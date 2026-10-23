# Challenge B architecture

## B1: session compaction

```text
Session messages + large tool outputs
  -> ContextMonitor (manual, milestone, token/message/repetition threshold)
  -> SessionCompactor (KEEP / TRUNCATE / DROP)
  -> structured checkpoint + archive of originals
  -> reconstructed active context
  -> OfflineAgent continuation
```

The compactor only promotes explicit evidence. It preserves the unresolved concurrent-refresh failure and the failed TTL attempt separately, so a hypothesis cannot silently become a conclusion. `evidence_ids` make each checkpoint field traceable to an original message. The archive is audit-only and is not an input to continuation.

When invoked with `--provider gemini`, the adapter submits precisely this reconstructed context to Gemini. Offline remains the default.

## B2: Code Mode

```text
Question -> agent selects run_code("aggregate_logs_v1")
         -> SafeLogRuntime: list_files -> read_file (raw stays local)
         -> LogAggregate: parse -> filter -> group -> count -> reference
         -> compact findings only -> agent answer
```

The native baseline follows the contrasting boundary: every `read_file` result is considered model-visible. It uses the same aggregate algorithm only to compare accuracy fairly. The safe runtime accepts only a named program allowlist, resolves paths beneath the log root, and rejects arbitrary commands, missing files, traversal and timeout.

With `--provider gemini`, the adapter receives `QUESTION` plus `STRUCTURED_FINDINGS` after `run_code` finishes; raw logs and runtime intermediate reads remain outside that request.
