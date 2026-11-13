import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from database.storage import database_url


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {}, clear=True).start()
        patch('database.storage.Path.cwd', return_value=self.root).start()

    def create_db(self, path, xp):
        path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE users (xp INTEGER)')
            db.execute('INSERT INTO users VALUES (?)', (xp,))

    def read_xp(self, path):
        with sqlite3.connect(path) as db:
            return db.execute('SELECT xp FROM users').fetchone()[0]

    def test_new_database_and_stable_path(self):
        url = database_url(self.root)
        self.assertEqual(url.database, str(self.root / 'data/db.sqlite3'))
        self.create_db(Path(url.database), 100)
        with patch('database.storage.Path.cwd', return_value=self.root / 'elsewhere'):
            self.assertEqual(database_url(self.root), url)
        self.assertEqual(self.read_xp(url.database), 100)

    def test_legacy_database_survives_update_and_original_is_kept(self):
        old = self.root / 'db.sqlite3'
        self.create_db(old, 750)
        url = database_url(self.root)
        self.assertEqual(self.read_xp(url.database), 750)
        self.assertEqual(self.read_xp(old), 750)
        old.unlink()  # Simulate replacement of code outside persistent data.
        self.assertEqual(self.read_xp(database_url(self.root).database), 750)

    def test_persistent_database_wins_over_legacy(self):
        self.create_db(self.root / 'db.sqlite3', 10)
        self.create_db(self.root / 'data/db.sqlite3', 900)
        self.assertEqual(self.read_xp(database_url(self.root).database), 900)

    def test_old_explicit_default_is_migrated(self):
        os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:///db.sqlite3'
        self.create_db(self.root / 'db.sqlite3', 12)
        self.assertEqual(self.read_xp(database_url(self.root).database), 12)

    def test_custom_url_and_memory_are_preserved(self):
        for value in ('sqlite+aiosqlite:///:memory:', 'sqlite+aiosqlite:////app/data/custom.db'):
            os.environ['DATABASE_URL'] = value
            self.assertEqual(database_url(self.root), value)

    def test_data_directory_override(self):
        os.environ['DATA_DIR'] = str(self.root / 'persistent')
        self.assertEqual(database_url(self.root).database, str(self.root / 'persistent/db.sqlite3'))

    def test_ambiguous_legacy_files_are_not_guessed(self):
        other = self.root / 'other'
        self.create_db(self.root / 'db.sqlite3', 1)
        self.create_db(other / 'db.sqlite3', 2)
        with patch('database.storage.Path.cwd', return_value=other):
            with self.assertRaises(RuntimeError):
                database_url(self.root)
        self.assertFalse((self.root / 'data/db.sqlite3').exists())
