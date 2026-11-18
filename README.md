# claim-intake

A governed document intake prototype. It reads auto collision claim emails and
intake forms, extracts key fields with citations to the source lines, has a
named reviewer approve or correct them, and only then saves the exact approved
payload to a simulated claims system. It runs on synthetic data only.

**Stack:** Python 3.12, FastAPI, LangGraph, PostgreSQL 18, SQLAlchemy and
Alembic, uv, Docker Compose.

## Run it

You need Docker with Compose v2.

```sh
docker compose up --build
```

This starts PostgreSQL, runs the one shot `migrate` job (roles and schemas,
Alembic, LangGraph checkpoint tables), then starts the app on
<http://127.0.0.1:8000>. Check it:

```sh
curl http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0"}
```

API docs are at <http://127.0.0.1:8000/docs>. No `.env` is needed: `compose.yaml`
has local defaults for every value.

If port 5432 is already taken on your machine, start with `DB_PORT=55432 docker compose up --build`.

## Develop on the host (faster loop)

You need [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env          # host URLs point at localhost:5432
docker compose up -d db       # just the database
uv sync                       # create .venv from uv.lock
uv run python -m claim_intake.db.migrate
uv run uvicorn claim_intake.api.app:create_app --factory --reload
```

## Tests

Tests run against a real PostgreSQL. They read their database URLs from the
environment only, never from `.env`, so load it explicitly. With the database
up and `.env` in place:

```sh
uv run --env-file .env pytest
```

The run creates and migrates `claim_intake_test` if it does not exist. The test
database name must end in `_test`; the suite refuses anything else.

## Checks

Lint, format and type checks run on every commit once the hooks are installed,
and again in CI:

```sh
uv run pre-commit install         # once per clone: pre-commit and commit-msg hooks
uv run ruff check . && uv run ruff format .
uv run mypy                       # strict, on src/claim_intake
uv run pre-commit run --all-files
```

The hooks also block commits on `main` and reject any `Co-Authored-By` trailer.

## Configuration

Settings come from environment variables (a local `.env` is read too; real
variables win). A bad or missing value stops startup with one line per problem,
naming the setting but never its value.

| Variable | Used by | Notes |
| --- | --- | --- |
| `DATABASE_URL` | app | The `claim_app` role. Required. |
| `MIGRATE_DATABASE_URL` | migrate job | The `claim_owner` role. |
| `ADMIN_DATABASE_URL` | migrate job | Superuser, used only by bootstrap. |
| `TEST_DATABASE_URL` | tests | `claim_app` on a database ending in `_test`. |
| `LOG_LEVEL` | all | `DEBUG`, `INFO` (default), `WARNING`, `ERROR`. |

URLs use plain `postgresql://`. Logs go to stderr as one JSON object per line.

## Smoke check before you push

This proves the whole system boots with one command. It uses its own Compose
project name, so it never touches your development database volume.

```sh
DB_PORT=55432 docker compose -p claim-intake-smoke up -d --build
for i in $(seq 1 60); do curl -fsS http://127.0.0.1:8000/health && break; sleep 1; done
docker compose -p claim-intake-smoke down -v
```

## Upgrading PostgreSQL

A data volume from one major version will not start under another. On
synthetic data the simple path is to drop the volume and start fresh, which
**deletes all local data**:

```sh
docker compose down -v
docker compose up --build
```

## Layout

```text
src/claim_intake/
  api/            app factory, routers, middleware, /health
  graph/          LangGraph flow (feature 5)
  llm/            model client seam (feature 5)
  claims_system/  simulated claims system (feature 6)
  db/             engine, bootstrap, migrate command
  config.py       settings
  logging.py      JSON logging
migrations/       Alembic
tests/
```

## License

MIT, see [LICENSE](LICENSE).
