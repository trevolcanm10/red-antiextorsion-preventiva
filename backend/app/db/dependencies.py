from collections.abc import Generator

from sqlalchemy.orm import Session


def get_db() -> Generator[Session, None, None]:
    """Dependencia de FastAPI que provee una sesion de base de datos."""
    from app.db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
