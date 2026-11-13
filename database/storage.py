"""Stable SQLite location and non-destructive migration of the old default file."""
import logging
import os
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy.engine import URL


def database_url(project_root: Path):
    configured = os.getenv('DATABASE_URL', '').strip()
    if configured and configured != 'sqlite+aiosqlite:///db.sqlite3':
        return configured

    directory = Path(os.getenv('DATA_DIR') or project_root / 'data').resolve()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / 'db.sqlite3'
    if not target.exists():
        candidates = {path.resolve() for path in
                      (project_root / 'db.sqlite3', Path.cwd() / 'db.sqlite3')
                      if path.is_file() and path.resolve() != target}
        if len(candidates) > 1:
            raise RuntimeError('Найдено несколько старых db.sqlite3. Остановите бота и '
                               'выберите нужную базу для переноса в data/db.sqlite3.')
        if candidates:
            source = candidates.pop()
            # Finish the backup before exposing it; link refuses to replace a DB.
            descriptor, temporary = tempfile.mkstemp(prefix='.migration-', dir=directory)
            os.close(descriptor)
            try:
                with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as old:
                    with sqlite3.connect(temporary) as new:
                        old.backup(new)
                os.link(temporary, target)
            finally:
                Path(temporary).unlink()
            logging.info('Старая база скопирована из %s в %s; исходник сохранён', source, target)
    logging.info('SQLite: %s', target)
    return URL.create('sqlite+aiosqlite', database=str(target))
