# Judge mode

The Azure deployment enables Judge mode by default. The public web app starts the seeded `late_comeback` fixture at 10× playback with the analyst English, casual English, casual Spanish, and player-focus views. No login is required.

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

1. Open the web app URL from the deployment workflow output. The kickoff screen should say **Judge mode** and offer **START JUDGE MODE** without asking for an account.
2. Start the fixture. The match details endpoint should report scenario `late_comeback`, seed `1`, speed `10`, and all four profiles.
3. Connect two browser sessions to observe the same deployment; additional active matches should be rejected after the configured capacity is used.
4. For a controlled cost-guard check, use a nonproduction deployment with a low `MAX_LLM_CALLS_PER_MATCH`. Confirm the match continues with deterministic fallback cues and a `cost_guard` trace.
5. Start a match without connecting a viewer and confirm it transitions to `stopped` after the configured idle timeout.

Do not lower the live judge deployment's call budget for a test. The fixed production limit is 400 calls per match.
