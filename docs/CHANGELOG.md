# Changelog

All notable changes are recorded here, one section per milestone tag.

## [m0] — Scaffold

### Added

- Monorepo with a uv-managed Python 3.12 backend (`matchlens` package) and a Vite + React + TypeScript frontend.
- Typed settings for `LLM_MODE`, `TRANSPORT`, `STORE` and the cost-guard limits, offline by default, failing fast when a cloud mode lacks its endpoint.
- `matchlens info` CLI command showing the active runtime modes.
- GitHub Actions CI: ruff, pyright (strict), pytest with coverage, ESLint, tsc, Vitest, production build, `pip-audit` and `npm audit`.
- Dependabot for uv, npm and GitHub Actions.
- Secret scanning with gitleaks: a pre-commit hook on staged changes and a CI job over the full git history (`make secrets-scan`).
- Makefile, `.env.example`, pre-commit hooks and EditorConfig.
