# Experimental evidence

## Environment and methodology

Run on 2026-10-23 with Python 3.12 in offline mode:

```powershell
python -m unittest discover -s tests -v
python context_harness.py demo:b1 --output-dir demo-output
python context_harness.py demo:b2 --output-dir demo-output
```

The B2 generator seed is `20261023`. Token numbers are estimates: B1 uses a transparent regex token counter; the native baseline uses bytes/4. No model provider was called and no provider usage is reported. The optional Gemini adapter was tested only with an injected mock transport; no real key or network call was used.

## Observed B1 result

| Measure | Before | After |
| --- | ---: | ---: |
| Messages | 14 | 3 |
| Regex token estimate | 1,410 | 238 |
| Reduction | — | 83.12% |
| Raw tool-output messages active | 6 | 0 |

The emitted checkpoint retained the goal, backward-compatibility constraint, verified concurrent-refresh failure, TTL failed attempt, `auth.ts`/`session.ts`/`auth.test.ts`, and locking next action. The resumed policy selected locking/single-flight investigation and explicitly did not retry TTL. Test `test_no_raw_context_reinjection` verified the archived `STACK_TRACE` and repeated output were absent from reconstructed context.

## Observed B2 result

| Measure | Native read-to-context baseline | Code Mode |
| --- | ---: | ---: |
| Files processed | 60 | 60 |
| Event entries processed | 5,400 | 5,400 |
| Tool calls | 61 | 1 visible to agent; 61 inside runtime |
| Raw log bytes exposed to LLM | 659,695 | 0 |
| Input token estimate | 164,924 | 1,217 |
| Aggregate matches generated ground truth | yes | yes |

For this deterministic run, the most frequent errors were `DB_TIMEOUT` (841), `AUTH_INVALID_CREDENTIALS` (587), and `REFRESH_TOKEN_RACE` (452). These are runtime-derived, not embedded as expected answers. The generated JSON reports hold references (file:line) for manual audit.

## Limitations

The deterministic offline policy proves harness state and boundary behavior, not an LLM's reasoning quality. To validate a particular provider/model, replace `OfflineAgent` with that provider and record provider-reported usage separately; do not compare its usage with the estimates above as if they were equivalent.

The repository now includes an opt-in Gemini adapter. It requires `GEMINI_API_KEY` only when `--provider gemini` is selected, sends B1 reconstructed context or B2 structured findings only, and has three provider-boundary tests. The full suite has 13 passing tests.
