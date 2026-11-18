"""The FastAPI app factory.

Run with `uvicorn claim_intake.api.app:create_app --factory`. Settings are built
here, so a bad value stops the process before it serves anything.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from claim_intake import __version__
from claim_intake.api import health
from claim_intake.api.middleware import RequestIdMiddleware
from claim_intake.config import Settings, load_or_exit
from claim_intake.db.engine import make_engine
from claim_intake.logging import configure

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    if settings is None:
        settings = load_or_exit(Settings)
    # The Uvicorn CLI cannot pass log_config=None, so this replaces Uvicorn's
    # handlers instead: the factory runs before Uvicorn logs its first line.
    configure(settings.log_level)
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("claim-intake %s starting", __version__)
        yield
        engine.dispose()
        logger.info("claim-intake stopped")

    app = FastAPI(title="claim-intake", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    return app
