# Changelog

All notable changes are recorded here, one section per milestone tag.

## [m1] — Fictional world and simulator (in progress)

### Added

- Data contracts as frozen, strict Pydantic models: match metadata, match clock, events (a discriminated union with typed outcome and attrs per event type), tracking frames, metric snapshots, moments, insights, claims, viewer profiles, overlay cues, recaps, agent traces and the WebSocket envelope.
- `matchlens schemas export` and `make schemas`: JSON Schema (draft 2020-12) for every contract in `docs/schemas/`, with a test that fails when the committed schemas drift.
- Fictional Meridian League: 4 clubs (possession, pressing, direct and balanced styles; 4-3-3, 4-2-3-1, 4-4-2, 4-1-4-1) with 18 invented players each. `Club.as_team(side)` builds the side-specific `Team` contract.

## [m0] — Scaffold

### Added

- Monorepo with a uv-managed Python 3.12 backend (`matchlens` package) and a Vite + React + TypeScript frontend.
- Typed settings for `LLM_MODE`, `TRANSPORT`, `STORE` and the cost-guard limits, offline by default, failing fast when a cloud mode lacks its endpoint.
- `matchlens info` CLI command showing the active runtime modes.
- GitHub Actions CI: ruff, pyright (strict), pytest with coverage, ESLint, tsc, Vitest, production build, `pip-audit` and `npm audit`.
- Dependabot for uv, npm and GitHub Actions.
- Secret scanning with gitleaks: a pre-commit hook on staged changes and a CI job over the full git history (`make secrets-scan`).
- Makefile, `.env.example`, pre-commit hooks and EditorConfig.
