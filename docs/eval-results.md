# MatchLens evaluation

Mode: `mock` · Fault rate: `0.0` · Matches: 9

| Measure | Result |
| --- | ---: |
| Unverified numeric claims shipped | 0 |
| Faults caught / injected | 0 / 0 |
| Fault catch rate | n/a |
| First-pass verification rate | 90.8% |
| Fallback rate | 0.0% |
| Moments per match, mean | 26.67 |
| Insight latency p50 / p95 (ms) | 1.55 / 2.93 |
| LLM calls | 806 |
| Estimated input / output tokens | 277105 / 35120 |

Insight latency measures Detector selection to completed verification in this offline harness. Cue delivery, profiles and cost estimation are planned for later milestones. Mock token counts are character-based estimates.

| Scenario | Seed | Moments | First pass | Fallbacks | Claims | Faults caught / injected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| balanced | 1 | 27 | 27 | 0 | 20 | 0 / 0 |
| balanced | 2 | 29 | 28 | 0 | 23 | 0 / 0 |
| balanced | 3 | 24 | 20 | 0 | 20 | 0 / 0 |
| late_comeback | 1 | 30 | 23 | 0 | 26 | 0 / 0 |
| late_comeback | 2 | 26 | 23 | 0 | 26 | 0 / 0 |
| late_comeback | 3 | 27 | 26 | 0 | 24 | 0 / 0 |
| red_card_press | 1 | 27 | 26 | 0 | 23 | 0 / 0 |
| red_card_press | 2 | 23 | 20 | 0 | 20 | 0 / 0 |
| red_card_press | 3 | 27 | 25 | 0 | 23 | 0 / 0 |
