"""Declarative base for ORM models, shared by `db.models` and `claims_system.models`.

One `Base` means one MetaData: the naming convention gives every constraint a
stable name (so Alembic autogenerate can drop and alter them reliably), and
`migrations/env.py` sees every table through a single `target_metadata`.
"""

from enum import StrEnum

from sqlalchemy import Enum, MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

STATE_LENGTH = 32


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def state_column(enum_cls: type[StrEnum], name: str) -> Enum:
    """A state column type: text plus a named CHECK limited to the enum's values.

    Text rather than a native Postgres enum, so adding a value later is a plain
    CHECK swap, not an `ALTER TYPE`. `name` becomes the CHECK name through the
    naming convention (`ck_<table>_<name>`); pass the column's own name.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        length=STATE_LENGTH,
        values_callable=lambda e: [m.value for m in e],
        name=name,
    )
