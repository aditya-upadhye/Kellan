# Changelog

All notable changes are recorded here, one section per milestone tag.

## [Unreleased] — M5 verified insights

### Added

- Explainer agent requests a structured narrative and evidence claims through the strong-model LLM client. It supplies one moment, evidence snapshots, score, minute, allowed names and the three most recent insights, then wraps the response in a draft `Insight` with stable IDs.
- Deterministic claim verification checks historical metric values at each claim's `as_of_seq`, displayed rounding and units, evidence membership, exact text spans, uncited digits and English number words, and headline/body limits. It returns structured error codes for the retry stage.
- Fact-Checker retries rejected drafts up to twice with structured verifier errors, records rejection and retry traces, and approves only drafts with no verification errors. Disabled or failed model calls and exhausted retries use a deterministic moment template; metric evidence is included only when the completed template passes the same verifier.
- `FAULT_INJECT_RATE` deterministically corrupts one claim value on the first draft of a selected moment before verification. The checker traces the injection, rejects the mismatched claim, and allows a corrected revision or safe fallback. A zero rate leaves drafts untouched.

## [m4] — LLM layer and deterministic moment detection

### Added

- Deterministic goal, card, big chance, momentum, pressing, control, speed and milestone triggers, plus periodic player spotlights.
- Candidate merging for nearby moments with matching types and subjects; goals and cards remain independent.
- Detector agent reviews pending candidates every 15 match seconds, passes goals and cards immediately, and selects at most one noncritical cue per five match minutes. Disabled, unavailable or invalid model responses fall back to rule significance.
- Mock batch fixtures can derive decisions from candidate IDs, so full match checks exercise mock decisions instead of the fallback path.
- OpenTelemetry spans cover LLM requests and Detector reviews. AgentTrace records share their active trace ID, and the API starts a console exporter for local inspection.

### Verified

- Full tracking matches across `balanced`, `late_comeback` and `red_card_press` with seeds 1, 2 and 3 produced 23–30 moments in both off and mock modes. Mock decisions completed without fallback. The five-minute noncritical interval was chosen after the two-minute and four-minute intervals exceeded the 30-moment target.
- Console span export and trace correlation pass focused tests. On 2026-10-11 at 22:09 UTC, `scripts/check_foundry.py` made a successful local structured-output call to the `gpt-4.1-mini` Foundry deployment. The provider reported model `gpt-4.1-mini-2025-04-14`, 49 input tokens and 6 output tokens. Its provider span and MatchLens LLM span printed through the console exporter with the same trace ID, and the script printed `Foundry call succeeded`.

## [m3] — Live match view

### Added

- Local FastAPI match lifecycle endpoints and a WebSocket stream for status, events, tracking frames and metric snapshots.
- React live match view with scenario and seed selection, playback controls, scoreboard, pitch tracking, metrics and event feed. Frontend contract types are generated from the committed JSON Schemas.
- Docker Compose stack with a health-checked API, static frontend, and HTTP/WebSocket proxy for a local full-stack demo.

## [m2] — Transport, store and metrics

### Added

- Local FIFO transport and an Azure Event Hubs publisher/consumer behind a shared protocol. Replay-session application properties isolate repeated plays of the same match ID. The Azure SDKs are pinned in the optional `azure` dependency group; `DefaultAzureCredential` supports local login and managed identity.
- In-memory and Azure Cosmos metric stores with historical `as_of_seq` lookup and per-window snapshots. Cosmos partitions by match ID.
- Incremental metric engine for goals, match and five-minute possession, team and player passing, pass difficulty, xG, shot and ball speed, ten-minute PPDA and field tilt, momentum, five-minute control, and frame-derived distance, top speed and sprint crossings. Count and ratio units were added to the generated schema.
- Replay CLI with 1×, 10×, 30×, 60× and max speeds, merging saved event and tracking streams by match clock. Hand-built metric tests and local stream-vs-batch parity checks are in place.

### Verified

- Live Event Hubs and Cosmos integration tests pass against Azure resources with Microsoft Entra ID credentials. Database and container provisioning is an infrastructure responsibility; the Cosmos runtime adapter uses data-plane access only. Azure tests remain marked `azure` and excluded from default CI.

## [m1] — Fictional world and simulator

### Added

- Data contracts as frozen, strict Pydantic models: match metadata, match clock, events (a discriminated union with typed outcome and attrs per event type), tracking frames, metric snapshots, moments, insights, claims, viewer profiles, overlay cues, recaps, agent traces and the WebSocket envelope.
- `matchlens schemas export` and `make schemas`: JSON Schema (draft 2020-12) for every contract in `docs/schemas/`, with a test that fails when the committed schemas drift.
- Fictional Meridian League: 4 clubs (possession, pressing, direct and balanced styles; 4-3-3, 4-2-3-1, 4-4-2, 4-1-4-1) with 18 invented players each. `Club.as_team(side)` builds the side-specific `Team` contract.
- Possession-chain match simulator (`sim/`): one seeded `random.Random`, formation-anchored team shapes with an offside line, pressure, passes, carries, dribbles, shots, tackles, interceptions, fouls, cards, penalties, corners, free kicks, throw-ins, goal kicks, 3–5 substitutions per team and 1–5 minutes of added time per half. All probabilities live in `EngineTuning`.
- Shared xG model (`metrics/xg.py`): logistic on distance and visible goal angle, header penalty, penalties fixed at 0.76. The simulator samples shot outcomes from it.
- 1 Hz tracking frames (`sim/tracking.py`) derived from the events and the shared team-shape model: ball flight timed from pass, shot and carry speeds; players accelerate at up to 3 m/s² toward shape targets, event locations or the ball; top speed from pace, reported speed from movement between frames and capped at 36 km/h; counter-attack surges; substitutes enter from the halfway line and sent-off players leave.
- `write_match` writes `metadata.json`, `events.jsonl` and `frames.jsonl`; same seed gives byte-identical files.
- Scenarios in `data/scenarios/*.yaml` (`balanced`, `late_comeback`, `red_card_press`): club pairing, starting style overrides and scripted injections (`red_card` and `force_goal` at a time, style `modify` from a time). `matchlens sim --scenario … --seed …` and `make sim`. New dependency: PyYAML, because scenarios are hand-authored YAML files.
- Simulator tests: byte-identical output for the same seed and scenario (also across processes with different hash seeds), realism targets over 50 seeds of `balanced`, Hypothesis property tests (sequence, clock, bounds, possession, speed cap) and a 5 s generation budget measured outside coverage. `make backend-test-fast` skips the `slow` tests; CI runs everything with an 80% coverage floor.

## [m0] — Scaffold

### Added

- Monorepo with a uv-managed Python 3.12 backend (`matchlens` package) and a Vite + React + TypeScript frontend.
- Typed settings for `LLM_MODE`, `TRANSPORT`, `STORE` and the cost-guard limits, offline by default, failing fast when a cloud mode lacks its endpoint.
- `matchlens info` CLI command showing the active runtime modes.
- GitHub Actions CI: ruff, pyright (strict), pytest with coverage, ESLint, tsc, Vitest, production build, `pip-audit` and `npm audit`.
- Dependabot for uv, npm and GitHub Actions.
- Secret scanning with gitleaks: a pre-commit hook on staged changes and a CI job over the full git history (`make secrets-scan`).
- Makefile, `.env.example`, pre-commit hooks and EditorConfig.
