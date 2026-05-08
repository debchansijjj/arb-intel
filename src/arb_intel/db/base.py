"""SQLAlchemy declarative base + общие type-aliases."""

from __future__ import annotations

from typing import Annotated

from sqlalchemy import BigInteger, DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, mapped_column

# Глобальная метадата с naming convention — alembic будет генерить
# консистентные имена индексов и FK.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


# часто используемые поля
str_addr = Annotated[str, mapped_column(String(96), index=True)]
str_short = Annotated[str, mapped_column(String(64), index=True)]
str_long = Annotated[str, mapped_column(String(256))]


def created_at_column():
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column():
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


def bigint_pk():
    return mapped_column(BigInteger, primary_key=True, autoincrement=True)
