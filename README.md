# MatchLens

MatchLens turns a synthetic football event stream into fact-checked, personalized on-screen insights.
Code computes every number, agents write every sentence, and a Fact-Checker agent guarantees the two agree.

Built for the Microsoft Premier League Hackathon (Inside the Game), Best Multi-Agent System category.
Everything in MatchLens is fictional: league, clubs, players and venues are invented.

> **Status:** M0 — scaffold. See [docs/CHANGELOG.md](docs/CHANGELOG.md) for progress.

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
