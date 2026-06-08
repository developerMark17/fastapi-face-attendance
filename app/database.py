from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

settings = get_settings()


class Base(DeclarativeBase):
    pass


# SQLite requires check_same_thread=False; ignored by other DB drivers
db_url = settings.database_url
if db_url.startswith("sqlite:///./"):
    from pathlib import Path
    backend_dir = Path(__file__).resolve().parent.parent
    db_file_name = db_url[len("sqlite:///./"):]
    db_path = backend_dir / db_file_name
    db_url = f"sqlite:///{db_path.as_posix()}"

_connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
engine = create_engine(db_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
