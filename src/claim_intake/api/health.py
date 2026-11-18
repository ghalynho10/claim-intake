"""`GET /health`: is the app up and can it reach the database?"""

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from claim_intake import __version__
from claim_intake.api.deps import EngineDep
from claim_intake.db.engine import ping

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str


@router.get(
    "/health",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Health, "description": "Database unreachable"}},
)
def health(engine: EngineDep, response: Response) -> Health:
    try:
        ping(engine)
    except SQLAlchemyError as exc:
        # The class name only: driver messages can name hosts and users.
        logger.warning("health check failed: %s", type(exc).__name__)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return Health(status="unavailable", version=__version__)
    return Health(status="ok", version=__version__)
