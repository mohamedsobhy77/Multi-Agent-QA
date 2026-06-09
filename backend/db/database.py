from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.config import get_settings
settings = get_settings()

# ── Engine ─────────────────────────────────────────────────────────────────────
#
# pool_pre_ping=True  — issues a lightweight SELECT 1 before handing a
#                        connection back from the pool, preventing stale-
#                        connection errors after a Postgres restart.
#
# echo=settings.DEBUG — logs every SQL statement when DEBUG=true; switch off
#                        in staging/production to avoid log noise.
#
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
)

# ── Session factory ────────────────────────────────────────────────────────────
#
# expire_on_commit=False — keeps ORM attributes accessible after commit
#                           without triggering a lazy-load (important in async
#                           context where lazy I/O raises MissingGreenlet).
#
AsyncSessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── Declarative base ───────────────────────────────────────────────────────────
#
# All ORM models inherit from this Base.
# Alembic's env.py imports it to access Base.metadata for autogenerate.
#
class Base(DeclarativeBase):
    pass


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yield a database session scoped to a single HTTP request.

    Commit lifecycle:
      - Happy path  → commit() is called after the endpoint returns.
      - Exception   → rollback() is called; the exception propagates.
      - Always      → session is closed in the finally block.

    Usage in an endpoint:

        @router.post("/example")
        async def example(db: AsyncSession = Depends(get_db)):
            db.add(MyModel(...))
            # No explicit commit needed — the dependency handles it.
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
