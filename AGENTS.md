# claim-intake

## Stack

- **Language / Runtime**: Python 3.12 (`>=3.12,<3.13`), image `python:3.12-slim`
- **Framework**: FastAPI on Uvicorn (sync endpoints, `create_app()` factory, one worker); LangGraph for the extract, review interrupt, save flow
- **Key dependencies**: PostgreSQL 18 · SQLAlchemy 2 + Alembic + psycopg 3 (sync) · `langgraph-checkpoint-postgres` · Pydantic v2 + `pydantic-settings` · Anthropic SDK behind a `ModelClient` Protocol · Jinja2 + HTMX for the review UI (feature 6)
- **Package manager**: uv (`uv_build` backend, `src/` layout, committed `uv.lock`)
- **Run / CI**: Docker Compose (`db`, one shot `migrate`, `app`); GitHub Actions `test` + `image` jobs
- Source of truth: spec 0001 (`docs/specs/0001-stack-and-architecture/`). Three schemas (`public`, `claims_system`, `langgraph`) and three roles (`claim_owner`, `claim_app`, `claim_mcp`).

## Build approach

**Tracer Bullet**: run one claim through every layer first, thin but real, then thicken one segment at a time.

## Commands

```bash
uv sync                                    # install (dev group included)
docker compose up --build                  # whole system, one command
docker compose up -d db && uv run python -m claim_intake.db.migrate   # host loop: db + migrate
uv run uvicorn claim_intake.api.app:create_app --factory --reload     # host loop: app
uv run pytest                              # tests (real Postgres; paid API tests need -m live)
# After /develop tooling installs them:
uv run ruff check . && uv run ruff format .
uv run mypy src/claim_intake
uv run lint-imports
uv run pre-commit run --all-files
```

## Specs

Stored in `docs/specs/NNNN-title/` (`index.md`, `rationale.md`, `verify.md`). `docs/` is private and gitignored: no code, image, CI step or public file may depend on a path under it.

## Rules

- Layered monolith with ports and adapters, as spec 0001 sets out. One package per layer: api (HTTP only), graph (the LangGraph workflow), llm (the ModelClient Protocol, its Anthropic implementation and a fake), claims_system (ClaimsSystemClient, the only code that touches claims_system tables), db (engine, session, models, bootstrap). Outside systems sit behind a Protocol with one real implementation and one fake for tests. Logic that needs no I/O (parsing, validation, scoring) is plain functions with typed inputs and outputs, tested without fakes. Prefer a plain function over a class where one works. No extra domain, application or infrastructure folders.
- Folders by layer, as the scaffold has them. `ui/`, `generator/`, `scoring/`, `mcp_server/` arrive with their features, never stubbed early.
- Strict typing: every function fully annotated, no implicit `Any`, mypy strict passes.
- Docstrings: a module docstring on every module, and one on public functions and classes saying why, not what.
- Errors: typed exceptions per layer; the api layer maps them to HTTP responses in one place; messages never echo secrets, URLs or claim values.
- Config comes from `pydantic-settings`, validated at startup; a bad value prints one line per setting (name, never value) and exits 1. Tunable settings arrive with the feature that first uses them.
- Logs: one JSON line per event to stderr from every entry point, with `request_id` and `claim_id`. Never log claim text or field values.
- UI meets WCAG AA: works by keyboard, labelled fields, readable contrast.
- Tests: pure logic gets unit tests with no fakes; DB, graph and API paths get integration tests against real Postgres, never a database mock. A feature ships with its tests. Paid model API tests carry the `live` marker, never run in CI, and run only after a measured cost estimate and the engineer's go. Tests never read the developer's `.env`: build settings explicitly and generate every password, key or token at test time with `secrets.token_hex(8)`.
- Conventional commit messages (`feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`).

## Tooling

Chosen here, installed by `/develop tooling`:
- **Ruff** for lint, import sorting and format (config in `pyproject.toml`).
- **mypy strict** with the official Pydantic plugin, run on `src/claim_intake`. Overrides only per untyped third party module, never a blanket ignore. No SQLAlchemy mypy plugin (deprecated in SQLAlchemy 2.0; `Mapped[]` models type check without it).
- **import-linter**, one `protected` contract: `protected_modules` is the claims_system table models, `allowed_importers` is `claim_intake.claims_system` only, so every other layer, including folders added later, is blocked without being listed. No other layer contracts until a real violation shows up.
- **pre-commit** on every commit: Ruff lint + format, mypy, import-linter, `no-commit-to-branch` for `main`, and a `commit-msg` hook that rejects any commit carrying a `Co-Authored-By` trailer.
- **CI**: one new `lint` job in the existing `.github/workflows/ci.yml` (ruff check, ruff format --check, mypy, lint-imports), same hardening: actions pinned by SHA, `contents: read`, `persist-credentials: false`. No second workflow file.

## Git

- integration: on
- branch prefix: feat/
- commit: per-milestone
- `main` is protected: never commit on it; work lands through a PR (`no-commit-to-branch` locally, a GitHub branch protection rule once the repo is on GitHub). Push and PRs always ask first.
- No `Co-Authored-By` trailer on any commit, and no "Generated with Claude Code" footer on PRs.

## Agent skills

Installed in `.agents/skills/` (gitignored, so these links resolve only on the engineer's machine):
- [fastapi](.agents/skills/fastapi/): `fastapi/fastapi`, FastAPI routes, dependencies, app structure
- [pydantic](.agents/skills/pydantic/): `pydantic/skills`, Pydantic v2 models, validation, settings
- [uv](.agents/skills/uv/): `astral-sh/agent-plugins`, uv envs, lockfile, commands
- [langchain-build-agent](.agents/skills/langchain-build-agent/): `langchain-ai/langchain-skills`, LangGraph guidance only; its Deep Agents advice is not adopted
- [docker-project-foundations](.agents/skills/docker-project-foundations/): `docker/skills`, Dockerfile, Compose and `.dockerignore` setup
- [docker-build-strategies](.agents/skills/docker-build-strategies/): `docker/skills`, multi stage builds, caching, non root images
- [docker-compose-patterns](.agents/skills/docker-compose-patterns/): `docker/skills`, services, healthchecks, dependency order
- [github-actions-hardening](.agents/skills/github-actions-hardening/): `github/awesome-copilot`, CI workflow security

Not yet chosen (offer when their feature starts): `sqlalchemy-alembic-expert-best-practices-code-review` (feature 3), `htmx`, `anthropic-claude-development`, `python-mcp-server-generator`, `postgresql-best-practices`, `pytest-coverage`.
MCP servers: none connected (GitHub MCP server skipped for now).

## Circuit breaker

If the same problem persists after one corrective prompt, stop and run /recover before trying
again. It diagnoses an isolated bug (routes to /debug), a session gone wrong through repeated
patching (hard reset), or a foundation resting on a wrong assumption (rethink).

/recover states its diagnosis without asking, but pauses for confirmation before a hard reset
ends the session or a rethink changes code. A hard reset note goes to `docs/session-notes.md`,
which /checkpoint reads and ages out.

## Context files

<!-- Nested AGENTS.md files are listed here as they are created -->

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._
