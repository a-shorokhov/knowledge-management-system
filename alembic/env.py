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
        # Preserve the application/test schema as the first search_path entry.
        # vector is shared across schemas; it must also be visible to reflection
        # and subsequent migrations, even when search_path names only a test schema.
        vector_schema = connection.scalar(text(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace WHERE e.extname = 'vector'"
        )) or "public"
        connection.execute(text(
            "SELECT set_config('search_path', current_setting('search_path') || ', ' || quote_ident(:schema), true)"
        ), {"schema": vector_schema})
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
