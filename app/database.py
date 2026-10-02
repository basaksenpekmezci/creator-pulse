"""
SQLAlchemy engine/session kurulumu. Geliştirmede SQLite, üretimde
DATABASE_URL'i Postgres'e çevirerek aynı kod tabanını kullanabilirsin.
"""
from sqlalchemy import create_engine, inspect, text
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


def add_missing_columns(bind) -> list[str]:
    """create_all yeni tabloları kurar ama var olan tablolara sonradan eklenen
    kolonları eklemez. Kullanıcı sistemiyle gelen kolonlar (users.password_hash,
    platform_accounts.sync_*) eski veritabanlarında yok; bunları burada
    ALTER TABLE ile ekliyoruz. Yeni kolonların hepsi boş bırakılabilir olduğu
    için mevcut satırlar bozulmaz. Eklenen kolonları "tablo.kolon" olarak döndürür."""
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())
    added = []
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=bind.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {column.name} {col_type}'))
                added.append(f"{table.name}.{column.name}")
    return added


def init_db(bind=None):
    # Modelleri import etmeden Base.metadata boş kalır, bu yüzden burada import ediyoruz.
    from app import models  # noqa: F401

    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    add_missing_columns(bind)
