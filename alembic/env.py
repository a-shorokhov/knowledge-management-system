from alembic import context
from sqlalchemy import text

import models
from core.database import Base, engine

config = context.config
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    return not (type_ == "table" and reflected and compare_to is None)


def run_migrations(connection):
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Миграции проекта предназначены для PostgreSQL")
    with connection.begin():
        connection.execute(text("SELECT pg_advisory_xact_lock(7419258301)"))
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Начальный переход требует подключения к PostgreSQL; режим --sql не поддерживается")

connection = config.attributes.get("connection")
if connection is not None:
    run_migrations(connection)
else:
    try:
        with engine.connect() as connection:
            run_migrations(connection)
    finally:
        engine.dispose()
