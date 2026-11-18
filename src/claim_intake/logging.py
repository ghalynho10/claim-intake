"""JSON line logging to stderr for every entry point.

Each line carries `ts`, `level`, `logger`, `msg`, `request_id`, `claim_id`, `exc`.
stderr keeps stdout free for an MCP stdio server. Never log claim text or field
values: log ids and counts instead.
"""

import json
import logging
import logging.config
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
claim_id_var: ContextVar[str | None] = ContextVar("claim_id", default=None)

# Requests to these paths stay out of the access log (container healthchecks
# poll them every few seconds).
QUIET_PATHS = frozenset({"/health"})


class ContextFilter(logging.Filter):
    """Copy the request id and claim id from context onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.claim_id = claim_id_var.get()
        return True


class QuietPathsFilter(logging.Filter):
    """Drop Uvicorn access log lines for health checks."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn's access record args: (client, method, path, http_version, status)
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            return args[2].split("?", 1)[0] not in QUIET_PATHS
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
            "claim_id": getattr(record, "claim_id", None),
            "exc": self.formatException(record.exc_info) if record.exc_info else None,
        }
        return json.dumps(entry, default=str)


def configure(level: str = "INFO") -> None:
    """Send all logs, Uvicorn's included, to stderr as JSON lines."""
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {
                "context": {"()": ContextFilter},
                "quiet_paths": {"()": QuietPathsFilter},
            },
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "stderr": {
                    "class": "logging.StreamHandler",
                    "stream": "ext://sys.stderr",
                    "formatter": "json",
                    "filters": ["context"],
                },
            },
            "root": {"level": level, "handlers": ["stderr"]},
            "loggers": {
                # Replace Uvicorn's own handlers so its lines are JSON too.
                "uvicorn": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.error": {"level": level, "handlers": [], "propagate": True},
                "uvicorn.access": {
                    "level": level,
                    "handlers": [],
                    "propagate": True,
                    "filters": ["quiet_paths"],
                },
                "httpx": {"level": "WARNING"},
                "anthropic": {"level": "WARNING"},
            },
        }
    )
