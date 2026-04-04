from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
import os

DATABASE_URL_RAW = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@db:5432/recipes")

# Ensure URL uses asyncpg driver
if "+asyncpg" not in DATABASE_URL_RAW:
    DATABASE_URL = DATABASE_URL_RAW.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = DATABASE_URL_RAW

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db():
    """Create tables if they don't exist (safe, won't drop data)"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db():
    async with async_session() as session:
        yield session
