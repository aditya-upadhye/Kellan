# Judge mode

The Azure deployment leaves fixture controls unlocked by default (`JUDGE_MODE=false`). Select **START JUDGE MODE PRESET** to start the seeded `late_comeback` fixture at 10× playback with the analyst English, casual English, casual Spanish, and player-focus views. No login is required. Set `JUDGE_MODE=true` only when the deployment should restrict every match to that preset.

Foundry playback uses the selected speed as an upper bound. If story generation falls behind, playback waits before pending evidence reaches the one-minute freshness cutoff. The UI says **Preparing the next insight** while this happens. Model latency can therefore make a 10× fixture take longer than one tenth of its simulated duration.

Each model request allows `LLM_REQUEST_ATTEMPTS=2` attempts with `LLM_REQUEST_TIMEOUT_SECONDS=12` seconds per attempt. `INSIGHT_GENERATION_TIMEOUT_SECONDS=90` bounds the complete insight workflow, after which checked templates provide a fallback. These settings do not guarantee Foundry availability or eliminate invalid model output.

## Deployment limits

| Setting | Default | Behavior |
| --- | ---: | --- |
| `MAX_CONCURRENT_MATCHES` | 2 | Rejects additional starts with HTTP 503 while the active-match limit is reached. |
| `MAX_LLM_CALLS_PER_MATCH` | 400 | Switches the match to `off` mode at the limit and records a `cost_guard` fallback trace. |
| `MAX_MATCH_STARTS_PER_IP_PER_HOUR` | 3 | Rejects further starts from the same client IP with HTTP 429 and a `Retry-After` header. |
| `MATCH_IDLE_TIMEOUT_SECONDS` | 900 | Stops a match that has no connected viewers for 15 minutes. |

The Azure web ingress forwards only the rightmost client address from `X-Forwarded-For` in a separate header. The API trusts that header only when `TRUST_PROXY_CLIENT_IP=true`; local development defaults to the direct connection address.

The in-memory limits apply per API process. The current Container Apps deployment keeps the API at one replica so its match capacity and start counters are shared by all requests to that deployment.

## Verify a deployment

1. Open the web app URL from the deployment workflow output. The kickoff screen should offer editable fixture controls and **START JUDGE MODE PRESET** without asking for an account.
2. Start the judge preset. The match details endpoint should report scenario `late_comeback`, seed `1`, speed `10`, and all four profiles.
3. Connect two browser sessions to observe the same deployment; additional active matches should be rejected after the configured capacity is used.
4. For a controlled cost-guard check, use a nonproduction deployment with a low `MAX_LLM_CALLS_PER_MATCH`. Confirm the match continues with deterministic fallback cues and a `cost_guard` trace.
5. Start a match without connecting a viewer and confirm it transitions to `stopped` after the configured idle timeout.

Do not lower the live judge deployment's call budget for a test. The fixed production limit is 400 calls per match.
