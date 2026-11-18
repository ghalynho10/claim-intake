"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import Engine


def get_engine(request: Request) -> Engine:
    """Hand routes the one engine the lifespan built, so tests can swap it per app."""
    engine: Engine = request.app.state.engine
    return engine


EngineDep = Annotated[Engine, Depends(get_engine)]
