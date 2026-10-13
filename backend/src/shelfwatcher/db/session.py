from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from src.shelfwatcher.config import settings

# Native PostgreSQL engine
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """FastAPI and service dependency to acquire database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
