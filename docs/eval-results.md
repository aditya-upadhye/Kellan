# Kellan evaluation

Mode: `mock` · Fault rate: `0.0` · Matches: 9

| Measure | Result |
| --- | ---: |
| Unverified numeric claims shipped | 0 |
| Faults caught / injected | 0 / 0 |
| Fault catch rate | n/a |
| First-pass verification rate | 93.3% |
| Fallback rate | 0.0% |
| Moments per match, mean | 26.67 |
| Insight latency p50 / p95 (ms) | 1.51 / 3.31 |
| LLM calls | 800 |
| Estimated input / output tokens | 243619 / 32095 |

Insight latency measures Detector selection to completed verification in this offline harness. Cue delivery, profiles and cost estimation are planned for later milestones. Mock token counts are character-based estimates.

| Scenario | Seed | Moments | First pass | Fallbacks | Claims | Faults caught / injected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| balanced | 1 | 27 | 26 | 0 | 20 | 0 / 0 |
| balanced | 2 | 29 | 27 | 0 | 23 | 0 / 0 |
| balanced | 3 | 24 | 23 | 0 | 20 | 0 / 0 |
| late_comeback | 1 | 30 | 26 | 0 | 26 | 0 / 0 |
| late_comeback | 2 | 26 | 24 | 0 | 26 | 0 / 0 |
| late_comeback | 3 | 27 | 23 | 0 | 24 | 0 / 0 |
| red_card_press | 1 | 27 | 27 | 0 | 23 | 0 / 0 |
| red_card_press | 2 | 23 | 22 | 0 | 20 | 0 / 0 |
| red_card_press | 3 | 27 | 26 | 0 | 23 | 0 / 0 |

## Foundry acceptance — 2026-10-12

The canonical nine-match run used `--scenarios all --seeds 1,2,3 --llm foundry --fault-rate 0`. It passed the M5 Foundry targets: first-pass verification was 90.8% (target ≥85%), fallback was 5.4% (target ≤10%), and no unverified numeric claims shipped. Insight latency was 1.70 s p50 and 5.64 s p95 (targets ≤3 s and ≤6 s).

| Scenario | Seed | Moments | First pass | Fallbacks | Claims | Faults caught / injected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| balanced | 1 | 27 | 25 | 1 | 25 | 0 / 0 |
| balanced | 2 | 29 | 26 | 0 | 40 | 0 / 0 |
| balanced | 3 | 24 | 24 | 0 | 25 | 0 / 0 |
| late_comeback | 1 | 30 | 25 | 5 | 47 | 0 / 0 |
| late_comeback | 2 | 26 | 22 | 2 | 43 | 0 / 0 |
| late_comeback | 3 | 27 | 24 | 3 | 36 | 0 / 0 |
| red_card_press | 1 | 27 | 26 | 0 | 46 | 0 / 0 |
| red_card_press | 2 | 23 | 21 | 1 | 32 | 0 / 0 |
| red_card_press | 3 | 27 | 25 | 1 | 38 | 0 / 0 |

The machine-readable Foundry outcomes are in [`eval/foundry-acceptance.json`](../eval/foundry-acceptance.json). Fault injection is validated separately by the nine-match mock run above: 191/191 corrupted claims caught, with zero unverified claims shipped.
