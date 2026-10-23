---
title: Challenge B Context Management implementation
status: completed
created: 2026-10-23
---

# Challenge B: Context Management plan

## Overview

Implement an offline, standard-library Python harness in `Challenge B/`. It will demonstrate two distinct boundaries: B1 compacts a long agent session into a traceable structured checkpoint; B2 lets a constrained runtime aggregate raw logs and returns only findings to the agent context.

## Scope

- In: executable CLI demos, deterministic log generator, B1/B2 harness, automated tests, architecture/evidence/requirement mapping.
- Out: Challenge A/C changes, web frontend, uncontrolled shell execution, invented LLM/API usage.

## Phases

| Phase | Status | Deliverable |
| --- | --- | --- |
| 1. B1 harness | completed | Session monitor, selective compaction, checkpoint, reconstruction and offline continuation |
| 2. B2 runtime | completed | Deterministic multi-file dataset, allowlisted runtime, aggregate findings and baseline |
| 3. Verification | completed | 10 `unittest` cases and regenerated demo artifacts |
| 4. Documentation | completed | README, architecture, evidence and requirement matrix |

## Acceptance criteria

1. B1 reduces active context while preserving goal, constraints, failure, failed attempt, files and next action; continuation chooses locking investigation from reconstructed context only.
2. B2 processes many generated logs inside an allowlisted runtime, returns structured findings only, and compares exposed raw data with a native-read baseline.
3. Tests cover context reduction/integrity/no reinjection and aggregation/leakage/safety.
4. `demo:b1`, `demo:b2`, and tests run with Python 3.11+ and no third-party dependency.

## Design decisions

- Use an explicit deterministic offline policy rather than claiming an LLM call occurred. It validates the actual checkpoint/findings it receives.
- Token figures are labeled estimates, using a transparent regex tokenizer; provider token usage is unavailable offline.
- `run_code` is a named analysis program, not arbitrary shell or Python evaluation. File reads resolve through an allowlisted dataset root, resource and time limits.
