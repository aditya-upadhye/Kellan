# Changelog

All notable changes are recorded here, one section per milestone tag.

## [m1] — Fictional world and simulator (in progress)

### Added

- Data contracts as frozen, strict Pydantic models: match metadata, match clock, events (a discriminated union with typed outcome and attrs per event type), tracking frames, metric snapshots, moments, insights, claims, viewer profiles, overlay cues, recaps, agent traces and the WebSocket envelope.
- `matchlens schemas export` and `make schemas`: JSON Schema (draft 2020-12) for every contract in `docs/schemas/`, with a test that fails when the committed schemas drift.
- Fictional Meridian League: 4 clubs (possession, pressing, direct and balanced styles; 4-3-3, 4-2-3-1, 4-4-2, 4-1-4-1) with 18 invented players each. `Club.as_team(side)` builds the side-specific `Team` contract.
- Possession-chain match simulator (`sim/`): one seeded `random.Random`, formation-anchored team shapes with an offside line, pressure, passes, carries, dribbles, shots, tackles, interceptions, fouls, cards, penalties, corners, free kicks, throw-ins, goal kicks, 3–5 substitutions per team and 1–5 minutes of added time per half. All probabilities live in `EngineTuning`.
- Shared xG model (`metrics/xg.py`): logistic on distance and visible goal angle, header penalty, penalties fixed at 0.76. The simulator samples shot outcomes from it.
- 1 Hz tracking frames (`sim/tracking.py`) derived from the events and the shared team-shape model: ball flight timed from pass, shot and carry speeds; players accelerate at up to 3 m/s² toward shape targets, event locations or the ball; top speed from pace, reported speed from movement between frames and capped at 36 km/h; counter-attack surges; substitutes enter from the halfway line and sent-off players leave.
- `write_match` writes `metadata.json`, `events.jsonl` and `frames.jsonl`; same seed gives byte-identical files.

## [m0] — Scaffold

### Added

- Monorepo with a uv-managed Python 3.12 backend (`matchlens` package) and a Vite + React + TypeScript frontend.
- Typed settings for `LLM_MODE`, `TRANSPORT`, `STORE` and the cost-guard limits, offline by default, failing fast when a cloud mode lacks its endpoint.
- `matchlens info` CLI command showing the active runtime modes.
- GitHub Actions CI: ruff, pyright (strict), pytest with coverage, ESLint, tsc, Vitest, production build, `pip-audit` and `npm audit`.
- Dependabot for uv, npm and GitHub Actions.
- Secret scanning with gitleaks: a pre-commit hook on staged changes and a CI job over the full git history (`make secrets-scan`).
- Makefile, `.env.example`, pre-commit hooks and EditorConfig.
