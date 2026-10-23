---
title: Challenge B optional Gemini provider
status: completed
created: 2026-10-23
---

# Challenge B optional Gemini provider

## Overview

Add a zero-dependency, opt-in Gemini adapter to the existing Challenge B CLI. Offline behavior remains the default and no credential is written to the repository.

## Phases

| Phase | Status | Deliverable |
| --- | --- | --- |
| Provider adapter | completed | Environment loader, authenticated REST client, bounded error handling |
| CLI integration | completed | `--provider`/`--gemini-model` applied to B1 and B2 prompt boundaries |
| Verification | completed | Mock transport tests, offline regression tests and documentation |

## Acceptance criteria

1. A user can copy `.env.example` to `.env`, set `GEMINI_API_KEY`, and run either demo with `--provider gemini`.
2. B1 sends only reconstructed context, while B2 sends only structured findings, to Gemini.
3. No API key appears in stdout, reports, errors, source, or tests; without a key, `--provider gemini` fails clearly before network access.
4. Existing offline commands and all tests remain functional.

## Scope

Gemini REST `generateContent` via the standard library only. No live API request, no key, no provider usage claim, and no change to B1/B2 runtime boundaries.
