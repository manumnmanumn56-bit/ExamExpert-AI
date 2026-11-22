"""
ExamExpert AI — SQLAlchemy Database Engine
SJB Institute of Technology | Office of Controller of Examinations
"""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.environ.get("EXAMEXPERT_DB_PATH", os.path.join(BASE_DIR, "examexpert.db"))
DATABASE_URL = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def rebind_engine(new_url: str):
    """Dynamically rebinds engine and SessionLocal to a temporary test database."""
    global engine, SessionLocal, DATABASE_URL
    DATABASE_URL = new_url
    engine.dispose()
    engine = create_engine(new_url, connect_args={"check_same_thread": False})
    SessionLocal.configure(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
