# MatchLens

MatchLens turns a synthetic football event stream into fact-checked, personalized on-screen insights.
Code computes every number, agents write every sentence, and a Fact-Checker agent guarantees the two agree.

Built for the Microsoft Premier League Hackathon (Inside the Game), Best Multi-Agent System category.
Everything in MatchLens is fictional: league, clubs, players and venues are invented.

> **Status:** M1 is tagged; M2 transport, store and metrics are under development on `m2-metrics`. See [docs/CHANGELOG.md](docs/CHANGELOG.md) for progress.

## Repository layout

| Path | Contents |
| --- | --- |
| `backend/` | Python 3.12 package `matchlens`, managed with uv |
| `frontend/` | React + Vite + TypeScript web client |
| `docs/` | Architecture, changelog, eval results, demo script |
| `.github/workflows/` | CI: lint, typecheck, tests, build and dependency audit |

## Prerequisites

- [uv](https://docs.astral.sh/uv/) 0.12+ (installs Python 3.12 automatically)
- Node.js 22 and npm
- GNU Make
- [gitleaks](https://github.com/gitleaks/gitleaks) 8.30+ for `make secrets-scan` (the pre-commit hook builds its own)

No cloud account is needed. By default every component runs locally with a mock LLM.

## Quick start

```bash
cp .env.example .env
make setup   # backend and frontend dependencies, pre-commit hooks
make lint    # ruff, pyright, eslint, tsc
make test    # pytest with coverage, vitest
make backend-test-fast   # quick loop: skips the slow simulation tests
```

Run `make help` to list every target.

On Windows without Make, the same steps run directly:

```powershell
uv sync --directory backend --locked
npm --prefix frontend ci
uv run --directory backend pytest --cov
npm --prefix frontend test
```

## Configuration

Settings are read from environment variables or a `.env` file; see [.env.example](.env.example).
Each cloud dependency sits behind an interface with a local default:

| Variable | Local default | Cloud value |
| --- | --- | --- |
| `LLM_MODE` | `mock` (or `off`) | `foundry` |
| `TRANSPORT` | `local` | `eventhubs` |
| `STORE` | `memory` | `cosmos` |

Selecting a cloud mode requires its endpoint settings; startup fails fast if they are missing.

```bash
uv run --directory backend matchlens info   # print the active modes
```

## Simulating a match

The simulator plays a fictional Meridian League fixture from a scenario in [data/scenarios/](data/scenarios/) and writes `metadata.json`, `events.jsonl` and `frames.jsonl` (1 Hz tracking) to `data/samples/<match_id>/`.

```bash
make sim SCENARIO=late_comeback SEED=42
# or: uv run --directory backend matchlens sim --scenario late_comeback --seed 42 [--events-only]
```

| Scenario | Fixture | What happens |
| --- | --- | --- |
| `balanced` | Kestrel Bay Athletic v Ashmoor Rovers | Possession against pressing, nothing scripted |
| `late_comeback` | Vellmont City v Kestrel Bay Athletic | Visitors lead two-nil; hosts press from 60' and score three late |
| `red_card_press` | Port Halden FC v Kestrel Bay Athletic | Away red card at 55'; hosts raise their press from 60' |

The same scenario and seed always produce byte-identical files. `DATA_DIR` overrides where scenarios are read from and samples are written to (default: the repository's `data/`).

## Replaying and computing metrics

Replay a saved match through the local queue and in-memory historical metric store:

```bash
uv run --directory backend matchlens replay ../data/samples/balanced-s42 --speed max
# Supported speeds: 1, 10, 30, 60, max (match-clock multiplier)
```

From `backend/` on Windows, use `.venv/Scripts/python.exe -m matchlens.cli replay ../data/samples/balanced-s42 --speed max`.
The replay command prints snapshot count, score and xG. It merges events and 1 Hz tracking by match clock, with events first on a tied timestamp. The metrics engine emits snapshots only when a value changes and retains sequence history for `get(match_id, metric_id, as_of_seq)`. Rolling possession, PPDA, field tilt and control windows use match time; PPDA is zero when there are no defensive actions in the window.

For Azure adapters, install `uv sync --directory backend --locked --extra azure`, set `TRANSPORT=eventhubs` and/or `STORE=cosmos`, and provide the endpoint settings from `.env.example`. Azure authentication uses `DefaultAzureCredential` (for example, `az login` locally or managed identity in Azure). Replay uses an Event Hubs application property to isolate runs of the same saved match. `pytest -m azure` runs live Event Hubs and Cosmos checks when their endpoint variables and resources are available; default CI skips them.

## Data contracts

Every payload that crosses a boundary (events, tracking frames, metric snapshots, insights, cues, recaps, traces) is a Pydantic model in `backend/src/matchlens/models/`.
The JSON Schemas in [docs/schemas/](docs/schemas/) are generated from those models; the frontend derives its TypeScript types from them.

```bash
make schemas   # or: uv run --directory backend matchlens schemas export --output-dir ../docs/schemas
```

A test fails if the committed schemas drift from the models.
