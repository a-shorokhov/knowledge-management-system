from contextlib import contextmanager

from sqlalchemy.orm import Session


@contextmanager
def transaction(db: Session):
    try:
        yield
        db.commit()
    except Exception:
        db.rollback()
        raise
