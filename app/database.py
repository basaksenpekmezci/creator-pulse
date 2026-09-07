"""
SQLAlchemy engine/session kurulumu. Geliştirmede SQLite, üretimde
DATABASE_URL'i Postgres'e çevirerek aynı kod tabanını kullanabilirsin.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

settings = get_settings()

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    # Modelleri import etmeden Base.metadata boş kalır, bu yüzden burada import ediyoruz.
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
