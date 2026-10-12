# Changelog

All notable changes are recorded here, one section per milestone tag.

## [Unreleased] - M6 personalization

### Added

- Added seeded analyst English, casual English, casual Spanish, and player-focus profiles. The API lists profiles at `GET /api/profiles` and retrieves one by ID at `GET /api/profiles/{profile_id}`.
- Added English and Spanish Personalizer prompts. Both accept only verified source insights and claims from that source. They can omit claims, but emitted values are rendered from allowed claims and rechecked against stored metrics with language-specific number-word parsing.
- Added localized, verified fallback templates for every moment type. Invalid or unavailable model output resolves to a number-free fallback; player-focus moments without the favorite player are skipped.

### Verified

- Profile seeds satisfy the strict `ViewerProfile` contract, and API tests cover list, lookup, and unknown IDs.
- Personalizer and verifier tests cover claim preservation and omission, English and Spanish number words, re-verification retries, localized fallback, casual limits and jargon, profile-specific presentation, and player-focus filtering.

## [m5] - Verified insights

### Added

- Explainer agent requests a structured narrative and evidence claims through the strong-model LLM client. It supplies one moment, evidence snapshots, score, minute, allowed names and the three most recent insights, then wraps the response in a draft `Insight` with stable IDs.
- Deterministic claim verification checks historical metric values at each claim's `as_of_seq`, displayed rounding and units, evidence membership, exact text spans, uncited digits and English number words, and headline/body limits. It returns structured error codes for the retry stage.
- Fact-Checker retries rejected drafts up to twice with structured verifier errors, records rejection and retry traces, and approves only drafts with no verification errors. Disabled or failed model calls and exhausted retries use a deterministic moment template; metric evidence is included only when the completed template passes the same verifier.
- `FAULT_INJECT_RATE` deterministically corrupts one claim value on the first draft of a selected moment before verification. The checker traces the injection, rejects the mismatched claim, and allows a corrected revision or safe fallback. A zero rate leaves drafts untouched.
- The M5 evaluation command replays full tracked matches through metrics, moments, Detector and fact-checked insights; it fails if an unverified insight or uncaught injected claim would ship. `make eval` writes a machine-readable report and a Markdown summary. The mock baseline covers three scenarios and three seeds; a separate fault run covers one seed per scenario.

### Verified

- Nine mock matches produced 240 moments and 205 verified numeric claims, with zero unverified claims, zero fallbacks and a 93.3% first-pass verification rate. A nine-match mock fault run caught 191/191 corrupted claims (100%), with zero unverified claims and zero fallbacks.
- The nine-match Foundry acceptance run produced 90.8% first-pass verification, 5.4% fallback, zero unverified claims, and p50/p95 latency of 1.70/5.64 seconds; all evaluation targets passed. Full backend suite: 388 passed, 2 Azure tests deselected. Ruff check, format check, and Pyright pass.

### Fixed

- The Explainer prompt now treats score and minute as internal context unless cited metric evidence supports displaying them. A live draft had correctly cited a control index but also included uncited `1:23` and "first half", causing the Fact-Checker to reject it. The one-call retest verified, but the full-match Foundry retest still missed the first-pass and fallback targets.
- The Explainer now receives the rejected draft during retries and cites exact text spans and matching metrics. A diagnostic across eight moment types exposed span mismatches and an incorrect goal citation. The verifier also recognizes `nil-nil` as a score expression. A focused sample exposed internal sequence IDs copied into viewer text. The Explainer now sends readable evidence under alphabetic keys and qualitative context to the model; code attaches metric IDs, values and sequence numbers to claims before strict verification. The provisional output scrubber was removed. Seven card moments have no metric evidence, so the prompt supports qualitative zero-claim insights. Across balanced, late_comeback and red_card_press seed-1, Foundry runs produced 84 moments, 74 first-pass approvals (88.1%), eight fallbacks (9.5%) and zero unsupported claims shipped. A separate four-card diagnostic passed every draft, leaving the full-match fallback causes unknown. It also exposed wrong player-to-club affiliations in two drafts. The Explainer now supplies each subject's club, and the evaluation JSON records per-moment verification outcomes for the next live run.
- A new late_comeback seed-1 Foundry run with per-moment outcomes identified all five fallbacks as goals: four exhausted retries on `uncited_number`, while one hit a model timeout after its first numeric rejection. It shipped zero unsupported claims but missed the per-scenario first-pass and fallback targets. A focused raw-draft diagnostic is needed to identify the offending numbers.
- The goal diagnostic found two displayed metrics but only one claim in each rejected draft. The one-claim prompt was inconsistent with goal insights that mention two statistics. It now permits a separate claim for each displayed metric, and the evidence payload names the team or player that owns each metric. One draft had incorrectly attributed the home club's possession to the away club; the numeric verifier could not detect that semantic error. Local integration coverage now checks two claims against their historical snapshots and the subject mapping. Live retest is pending.
- The focused live retest still found uncited numbers: one draft displayed a third metric while citing two, and another put the word "two" in its headline. The prompt no longer caps the number of relevant metrics; every displayed number requires its own claim, and headlines remain number-free. Retry feedback now names the exact offending expression and its location in the rejected draft without exposing verifier positions or internal metric IDs. A targeted retry diagnostic exercises the actual Fact-Checker loop before another full-match Foundry run.
- A retry-loop diagnostic verified one three-metric goal on its second attempt, confirming that exact numeric feedback works. It also revealed a unit-validation gap: `points` was accepted for an `index` metric because neither token was parsed as a unit. The verifier now compares `index`, `ratio`, `m`, and `points` semantics, and retries receive a safe `unit_mismatch` reason. Diagnostic mode now captures every rejected draft and full verifier errors for focused investigations without adding that content to product traces.
- A later retry diagnostic verified the remaining goal on its first attempt, but the prose called a negative control index "strong control." The trigger already classifies values below -25 as `chaos`; that shared interpretation now reaches the Explainer, which is instructed not to assign match-wide control to a club or contradict the state. The verifier also requires an explicit unit for non-count metrics.
- A focused retry run showed repeated `unsupported_claim` rejections: the model put both values from `2-0` in one claim and omitted `index` from two numeric claim spans. Retry feedback now names the offending multi-number span, and the prompt forbids inferred scorelines when only one side's goal count is evidence. The verifier recognizes unit labels before values in natural phrases such as "control index of -30.4". Focused regression tests cover those cases; live Foundry confirmation is pending.
- The next retry removed the scoreline but still omitted `index` in claim spans; another revision changed displayed precision without updating its spans. The prior feedback named only `unit_mismatch`, while `span_not_found` exposed an internal claim ID. Retry feedback now returns the corresponding previous claim text and expected unit, and the prompt explicitly requires exact claim substrings from the final body. Regression tests, the full backend suite, Ruff, formatting, and Pyright pass; a targeted Foundry retest remains pending.
- The focused late_comeback goal now verifies on attempt three without fallback. The first revision omitted both index units; the next corrected one unit but retained a stale span, and the final revision passed after receiving actionable span feedback. The focused fix is confirmed; the three-scenario live acceptance report is pending.
- The three-scenario seed-1 Foundry evaluation completed 84 moments with zero unverified numeric claims. First-pass verification was 52.4% (target >=85%) and fallback rate was 11.9% (target <=10%). Ten fallbacks were split evenly between goals and momentum swings; inspect raw drafts from both types before making another generation change.
- Per-moment outcomes show 40 moments needed a retry; 30 recovered and 10 fell back. Twenty first attempts were momentum swings with `span_not_found` and `uncited_number`; seven were goals with `unsupported_claim`. Use representative raw retries to identify why the model's spans drift or its claims fail before changing the prompt again.
- Raw retries revealed that the model changed a negative momentum value to positive while also omitting the unit. The verifier's unit/value `elif` chain reported only the unit problem, hiding the sign error from retry feedback. A goal draft also incorrectly inferred `chaos` from a momentum metric. Unit and value checks now run independently, retry feedback includes the supported value and evidence key, schema descriptions strengthen the exact-span contract, and `chaos` is scoped to an explicit control-index state. Full backend suite and static checks pass; targeted Foundry validation is pending.
- Targeted live validation confirmed the fix: the momentum swing verified on its first attempt with sign and unit intact; the goal's wrong-sign first draft was caught as `value_mismatch` and its second draft verified. Re-run the canonical nine-match Foundry evaluation (all scenarios, seeds 1–3) to measure the updated first-pass and fallback rates.
- Foundry first-pass verification stayed at 62.5-63.7% across two canonical runs, with failures concentrated in momentum swings, goals and press shifts. The Explainer no longer returns claims. Its response separates prose from evidence: the body is an ordered list of parts, each with prose and an optional evidence key, and code appends the value and unit rendered from the snapshot and builds the exact claim span. A focused live diagnostic showed the earlier prompt-only `{A}` convention was unreliable (the model typed `-39.2 index` into the prose, then dropped the metric), so it was replaced. The verifier stays strict: numbers in prose are `uncited_number`, braces typed into prose or an unknown key leave an unresolved reference that is `unsupported_claim`, and each displayed occurrence of a span needs its own claim. The Fact-Checker also rejects a draft that cites no metric when evidence was supplied, so prose-only output cannot satisfy the evidence requirement; moments without evidence are unaffected. A live Foundry retest is pending.
- A focused Foundry diagnostic of a momentum swing (`match.momentum` -39.2 index) cited the rendered value but described the wrong side and rendered `by-39.2`. Momentum swing evidence now includes the start reading as well as the end reading (`moment_evidence`), each marked with its phase. The Explainer also receives a momentum context that names which club positive and negative values favour, which club each reading favours, and which club the change moved toward, computed from the start-to-end difference and never from the end sign alone. Across the 104 swings in the nine mock matches the end sign alone would have given the wrong direction in 35. Rendered values get a space on each side when the prose does not already supply one; the cited span is unchanged. The diagnostic now shares the Fact-Checker's draft check (no-claim drafts with evidence are rejected) and prints a prompt hash and response fields so its output identifies the code that produced it.

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
