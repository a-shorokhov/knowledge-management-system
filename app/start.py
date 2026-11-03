import os
from pathlib import Path
import sys

from alembic import command
from alembic.config import Config


ROOT = Path(__file__).resolve().parent.parent


def main():
    command.upgrade(Config(str(ROOT / "alembic.ini")), "head")
    print("Миграции применены. Запуск API.", flush=True)
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "main:app", "--app-dir", str(ROOT / "app"), "--host", "0.0.0.0", "--port", "8000"])


if __name__ == "__main__":
    main()
