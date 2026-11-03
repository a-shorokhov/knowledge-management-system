"""Миграции проверяются отдельно от пользовательской БД и S3."""
import importlib.util
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import test_erd as test_runtime
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[1]


def migration_config(connection=None):
    config = Config(str(ROOT / 'alembic.ini'))
    if connection is not None:
        config.attributes['connection'] = connection
    return config


class MigrationConfigurationTests(unittest.TestCase):
    def test_single_revision_is_frozen_and_matches_models(self):
        scripts = ScriptDirectory.from_config(migration_config())
        self.assertEqual(scripts.get_heads(), ['0001_initial'])
        revision = scripts.get_revision('head')
        frozen = revision.module._schema()
        actual = test_runtime.database.Base.metadata
        self.assertEqual(set(frozen.tables), set(actual.tables))
        for name, table in actual.tables.items():
            self.assertEqual(set(frozen.tables[name].columns.keys()), set(table.columns.keys()))

    def test_start_runs_migrations_before_server_and_stops_on_failure(self):
        spec = importlib.util.spec_from_file_location('kms_start', ROOT / 'app' / 'start.py')
        start = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(start)
        events = []
        with patch.object(start.command, 'upgrade', side_effect=lambda *args: events.append('migration')), patch.object(start.os, 'execv', side_effect=lambda *args: events.append('server')):
            start.main()
        self.assertEqual(events, ['migration', 'server'])
        with patch.object(start.command, 'upgrade', side_effect=RuntimeError('migration failed')), patch.object(start.os, 'execv') as server:
            with self.assertRaises(RuntimeError):
                start.main()
            server.assert_not_called()


@unittest.skipUnless(os.environ.get('KMS_TEST_DATABASE_URL'), 'Для интеграционных проверок нужен отдельный PostgreSQL: KMS_TEST_DATABASE_URL')
class PostgreSQLMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine(os.environ['KMS_TEST_DATABASE_URL'], hide_parameters=True)
        self.schema = 'kms_migration_test_' + uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(sa.schema.CreateSchema(self.schema))
        self.connection = self.connect()

    def connect(self):
        connection = self.engine.connect()
        connection.execute(sa.text(f'SET search_path TO "{self.schema}"'))
        connection.commit()
        return connection

    def tearDown(self):
        self.connection.close()
        with self.engine.begin() as connection:
            connection.execute(sa.schema.DropSchema(self.schema, cascade=True))
        self.engine.dispose()

    def upgrade(self):
        self.connection.commit()
        command.upgrade(migration_config(self.connection), 'head')

    def assert_current(self):
        self.connection.commit()
        command.check(migration_config(self.connection))
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), '0001_initial')

    def legacy_data(self):
        statements = [
            "CREATE TABLE users (id SERIAL PRIMARY KEY, username VARCHAR(32) NOT NULL, email VARCHAR NOT NULL, hashed_password VARCHAR NOT NULL, CONSTRAINT uq_users_username UNIQUE(username), CONSTRAINT uq_users_email UNIQUE(email))",
            "CREATE TABLE modules (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, description TEXT)",
            "CREATE TABLE launches (id SERIAL PRIMARY KEY, module_id INTEGER NOT NULL REFERENCES modules(id) ON DELETE CASCADE, year INTEGER NOT NULL, title VARCHAR(255), description TEXT)",
            "CREATE TABLE materials (id SERIAL PRIMARY KEY, launch_id INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, description TEXT, original_filename VARCHAR(255) NOT NULL, storage_key TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
            "CREATE TABLE notes (id SERIAL PRIMARY KEY, launch_id INTEGER NOT NULL REFERENCES launches(id) ON DELETE CASCADE, title VARCHAR(255) NOT NULL, content TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now())",
            "CREATE TABLE templates (id SERIAL PRIMARY KEY, title TEXT)",
            "INSERT INTO users (username,email,hashed_password) VALUES ('old_user','old@example.com','original-hash')",
            "INSERT INTO modules (user_id,title) VALUES (1,'Existing module')",
            "INSERT INTO launches (module_id,year) VALUES (1,2025)",
            "INSERT INTO materials (launch_id,title,original_filename,storage_key) VALUES (1,'Lecture','lecture.txt','materials/keep/lecture.txt')",
            "INSERT INTO notes (launch_id,title,content) VALUES (1,'Note','Do not lose this text')",
            "INSERT INTO templates (title) VALUES ('Leave this table alone')",
        ]
        for statement in statements:
            self.connection.execute(sa.text(statement))
        self.connection.commit()

    def test_empty_database_repeat_upgrade_and_no_model_drift(self):
        self.upgrade()
        self.upgrade()
        self.assert_current()
        self.assertEqual(set(sa.inspect(self.connection).get_table_names()), set(test_runtime.database.Base.metadata.tables) | {'alembic_version'})

    def test_legacy_data_and_storage_keys_survive(self):
        self.legacy_data()
        self.upgrade()
        self.assert_current()
        self.assertEqual(self.connection.scalar(sa.text('SELECT hashed_password FROM users WHERE id=1')), 'original-hash')
        self.assertEqual(self.connection.scalar(sa.text('SELECT owner_id FROM modules WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT author_id FROM notes WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT content FROM notes WHERE id=1')), 'Do not lose this text')
        stored = self.connection.execute(sa.text('SELECT storage_key,mime_type,size_bytes FROM stored_files')).one()
        self.assertEqual(tuple(stored), ('materials/keep/lecture.txt', 'text/plain', 0))
        self.assertEqual(self.connection.scalar(sa.text('SELECT stored_file_id FROM materials WHERE id=1')), 1)
        self.assertEqual(self.connection.scalar(sa.text('SELECT title FROM templates')), 'Leave this table alone')
        self.connection.commit()
        self.upgrade()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM stored_files')), 1)

    def test_existing_erd_gets_missing_columns_and_cascades(self):
        test_runtime.database.Base.metadata.create_all(self.connection)
        self.connection.execute(sa.text('ALTER TABLE notes DROP COLUMN section_id CASCADE'))
        self.connection.execute(sa.text('ALTER TABLE stored_files DROP COLUMN deletion_pending'))
        self.connection.execute(sa.text('ALTER TABLE launches DROP CONSTRAINT fk_launch_module'))
        self.connection.execute(sa.text('ALTER TABLE launches ADD CONSTRAINT old_module_fk FOREIGN KEY (module_id) REFERENCES modules(id) ON DELETE RESTRICT'))
        self.connection.commit()
        self.upgrade()
        self.assert_current()

    def test_bad_data_rolls_back_entire_upgrade(self):
        self.legacy_data()
        self.connection.execute(sa.text('UPDATE launches SET year=0'))
        self.connection.commit()
        with self.assertRaises(sa.exc.IntegrityError):
            self.upgrade()
        columns = {item['name'] for item in sa.inspect(self.connection).get_columns('modules')}
        self.assertIn('user_id', columns)
        self.assertNotIn('owner_id', columns)
        self.assertEqual(self.connection.scalar(sa.text('SELECT storage_key FROM materials')), 'materials/keep/lecture.txt')
        self.assertNotIn('stored_files', sa.inspect(self.connection).get_table_names())
        self.assertNotIn('alembic_version', sa.inspect(self.connection).get_table_names())

    def test_conflicting_legacy_file_ownership_is_not_guessed(self):
        self.legacy_data()
        self.connection.execute(sa.text("INSERT INTO users (username,email,hashed_password) VALUES ('other','other@example.com','hash')"))
        self.connection.execute(sa.text("INSERT INTO modules (user_id,title) VALUES (2,'Other module')"))
        self.connection.execute(sa.text("INSERT INTO launches (module_id,year) VALUES (2,2026)"))
        self.connection.execute(sa.text("INSERT INTO materials (launch_id,title,original_filename,storage_key) VALUES (2,'Shared','lecture.txt','materials/keep/lecture.txt')"))
        self.connection.commit()
        with self.assertRaisesRegex(RuntimeError, 'разные владельцы'):
            self.upgrade()
        self.assertEqual(self.connection.scalar(sa.text('SELECT count(*) FROM materials')), 2)
        self.assertIn('user_id', {item['name'] for item in sa.inspect(self.connection).get_columns('modules')})
        self.assertNotIn('stored_files', sa.inspect(self.connection).get_table_names())

    def test_partial_unknown_schema_is_preserved(self):
        self.connection.execute(sa.text('CREATE TABLE users (id INTEGER PRIMARY KEY)'))
        self.connection.commit()
        with self.assertRaisesRegex(RuntimeError, 'неполная схема'):
            self.upgrade()
        self.assertEqual(sa.inspect(self.connection).get_table_names(), ['users'])

    def test_concurrent_startups_apply_initial_revision_once(self):
        code = f"""
import sys
sys.path.insert(0, {str(ROOT / 'tests')!r})
import test_erd
import os
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
engine = create_engine(os.environ['KMS_TEST_DATABASE_URL'], hide_parameters=True)
with engine.connect() as connection:
    connection.execute(text('SET search_path TO "{self.schema}"'))
    connection.commit()
    config = Config({str(ROOT / 'alembic.ini')!r})
    config.attributes['connection'] = connection
    command.upgrade(config, 'head')
engine.dispose()
"""
        processes = [subprocess.Popen([sys.executable, '-B', '-c', code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        try:
            for process in processes:
                stdout, stderr = process.communicate(timeout=30)
                self.assertEqual(process.returncode, 0, stderr)
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                    process.communicate()
        self.assert_current()

    def test_future_revision_keeps_existing_rows_and_runs_once(self):
        self.upgrade()
        self.connection.execute(sa.text("INSERT INTO users (username,email,hashed_password) VALUES ('kept','kept@example.com','kept-hash')"))
        self.connection.commit()
        with TemporaryDirectory() as directory:
            scripts = Path(directory) / 'alembic'
            shutil.copytree(ROOT / 'alembic', scripts)
            config = migration_config(self.connection)
            config.set_main_option('script_location', str(scripts))
            revision = command.revision(config, message='Добавить необязательное поле', rev_id='0002_test')
            path = Path(revision.path)
            path.write_text(path.read_text().replace('def upgrade():\n    pass', "def upgrade():\n    op.add_column('users', sa.Column('nickname', sa.String(50), nullable=True))"))
            command.upgrade(config, 'head')
            command.upgrade(config, 'head')
        user = self.connection.execute(sa.text('SELECT username,hashed_password,nickname FROM users')).one()
        self.assertEqual(tuple(user), ('kept', 'kept-hash', None))
        self.assertEqual(self.connection.scalar(sa.text('SELECT version_num FROM alembic_version')), '0002_test')
