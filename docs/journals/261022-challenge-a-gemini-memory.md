# Challenge A: Gemini-backed persistent memory

**Date:** 2026-10-22

## Context

Challenge A previously demonstrated persistent memory only through a deterministic offline response stub. The goal of this update was to make the same harness ready for a real Gemini model while preserving an offline, reproducible default.

## Changes

- Added Gemini `generateContent` support through the standard library, configured with `GEMINI_API_KEY` and `GEMINI_MODEL`.
- Sent the exact displayed `INJECTED_MEMORY` payload to Gemini, providing an auditable memory-to-LLM path.
- Added controlled `remember_convention` function calling, scoped retrieval, database/authentication conventions, environment examples, and updated documentation.

## Key decisions and guardrails

- Offline remains the default provider; Gemini is explicit opt-in.
- Model-proposed writes require `--allow-memory-write`; the harness validates topics/values and persists revisions itself.
- Retrieval limits active conventions by relevance and item count to reduce context growth; superseded revisions remain audit-only.
- Credential-shaped values are rejected before persistence or audit logging.

## Validation

Ran `python -m unittest discover -s tests -v`: **18 tests passed**. Tests include mocked Gemini prompt injection, guarded function calls, persistence, supersession, audit history, retrieval limits, and secret rejection.

## Remaining limitation

Secret detection is heuristic pattern scanning, not a complete credential-classification system; operational deployments should add stronger secret-management controls and review.
