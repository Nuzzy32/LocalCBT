from alembic import context

from app.db import engine

# Skema ditulis tangan di versions/ (SQL eksplisit), bukan autogenerate dari ORM.
with engine.connect() as connection:
    context.configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()
