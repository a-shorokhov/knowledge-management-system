from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.config import DB_URL


Base = declarative_base()
engine = create_engine(DB_URL, hide_parameters=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
