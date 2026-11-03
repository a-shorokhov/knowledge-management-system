from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _schema():
    metadata = sa.MetaData()
    sa.Table('users', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('username', sa.String(length=32), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('hashed_password', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email', name='uq_users_email'),
    sa.UniqueConstraint('username', name='uq_users_username')
    )
    sa.Table('modules', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    sa.Table('stored_files', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bucket', sa.String(length=255), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('original_filename', sa.String(length=255), nullable=False),
    sa.Column('mime_type', sa.String(length=255), nullable=False),
    sa.Column('size_bytes', sa.BigInteger(), nullable=False),
    sa.Column('uploaded_by_id', sa.Integer(), nullable=False),
    sa.Column('deletion_pending', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('indexing_status', sa.Enum('pending', 'processing', 'ready', 'failed', name='file_index_status'), server_default='pending', nullable=False),
    sa.Column('indexing_error_code', sa.String(length=100), nullable=True),
    sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('size_bytes >= 0', name='chk_file_size'),
    sa.ForeignKeyConstraint(['uploaded_by_id'], ['users.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bucket', 'storage_key', name='uq_stored_file_object')
    )
    sa.Table('launches', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('module_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('semester', sa.String(length=32), nullable=False),
    sa.Column('status', sa.Enum('draft', 'active', 'completed', name='run_status'), server_default='draft', nullable=False),
    sa.Column('copied_from_launch_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('copied_from_launch_id IS NULL OR copied_from_launch_id <> id', name='chk_run_copy_source'),
    sa.CheckConstraint('year > 0', name='chk_run_year'),
    sa.ForeignKeyConstraint(['copied_from_launch_id'], ['launches.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['module_id'], ['modules.id'], name='fk_launch_module', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    sa.Table('run_sections', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('launch_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.CheckConstraint('position >= 0', name='chk_section_position'),
    sa.ForeignKeyConstraint(['launch_id'], ['launches.id'], name='fk_sections_launch', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'launch_id', name='uq_section_id_run')
    )
    sa.Table('materials', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('launch_id', sa.Integer(), nullable=False),
    sa.Column('section_id', sa.Integer(), nullable=True),
    sa.Column('stored_file_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('kind', sa.Enum('plan', 'presentation', 'assignment', 'reading', 'feedback', 'other', name='material_kind'), server_default='other', nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('copied_from_material_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint('copied_from_material_id IS NULL OR copied_from_material_id <> id', name='chk_material_copy_source'),
    sa.CheckConstraint('position >= 0', name='chk_material_position'),
    sa.ForeignKeyConstraint(['copied_from_material_id'], ['materials.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['launch_id'], ['launches.id'], name='fk_materials_launch', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['section_id', 'launch_id'], ['run_sections.id', 'run_sections.launch_id'], name='fk_material_section_launch', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['stored_file_id'], ['stored_files.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('id', 'launch_id', name='uq_material_id_run')
    )
    sa.Table('notes', metadata,
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('launch_id', sa.Integer(), nullable=False),
    sa.Column('material_id', sa.Integer(), nullable=True),
    sa.Column('section_id', sa.Integer(), nullable=True),
    sa.Column('author_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['launch_id'], ['launches.id'], name='fk_notes_launch', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['material_id', 'launch_id'], ['materials.id', 'materials.launch_id'], name='fk_note_material_launch', ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['section_id', 'launch_id'], ['run_sections.id', 'run_sections.launch_id'], name='fk_note_section_launch', ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    sa.Index('ix_modules_owner_id', metadata.tables['modules'].c.owner_id, unique=False)
    sa.Index('ix_stored_files_uploaded_by_id', metadata.tables['stored_files'].c.uploaded_by_id, unique=False)
    sa.Index('ix_run_module_year', metadata.tables['launches'].c.module_id, metadata.tables['launches'].c.year, unique=False)
    sa.Index('ix_section_run_position', metadata.tables['run_sections'].c.launch_id, metadata.tables['run_sections'].c.position, unique=False)
    sa.Index('ix_material_run_position', metadata.tables['materials'].c.launch_id, metadata.tables['materials'].c.position, unique=False)
    sa.Index('ix_materials_section_id', metadata.tables['materials'].c.section_id, unique=False)
    sa.Index('ix_materials_stored_file_id', metadata.tables['materials'].c.stored_file_id, unique=False)
    sa.Index('ix_notes_launch_id', metadata.tables['notes'].c.launch_id, unique=False)
    sa.Index('ix_notes_material_id', metadata.tables['notes'].c.material_id, unique=False)
    sa.Index('ix_notes_section_id', metadata.tables['notes'].c.section_id, unique=False)
    return metadata


def _columns(connection, table):
    return {column['name'] for column in sa.inspect(connection).get_columns(table)}


def _prepare_existing(connection, metadata):
    tables = set(sa.inspect(connection).get_table_names())
    required = {'users', 'modules', 'launches', 'materials', 'notes'}
    if not required.issubset(tables):
        raise RuntimeError('Обнаружена неполная схема: ожидаются users, modules, launches, materials и notes. Данные не удалены')
    module_columns = _columns(connection, 'modules')
    if 'owner_id' not in module_columns and 'user_id' in module_columns:
        op.alter_column('modules', 'user_id', new_column_name='owner_id')
    for table in metadata.sorted_tables:
        if table.name not in tables:
            continue
        present = _columns(connection, table.name)
        if 'id' not in present:
            raise RuntimeError(f'Неизвестная структура таблицы {table.name}: отсутствует id')
        for column in table.columns:
            if column.name not in present:
                op.add_column(table.name, sa.Column(column.name, column.type, nullable=True, server_default=column.server_default))
    metadata.create_all(connection, checkfirst=True)
    connection.execute(sa.text("UPDATE modules SET description = '' WHERE description IS NULL"))
    connection.execute(sa.text("UPDATE launches SET title = year::text WHERE title IS NULL"))
    connection.execute(sa.text("UPDATE launches SET description = '' WHERE description IS NULL"))
    connection.execute(sa.text("UPDATE launches SET semester = 'Не указан' WHERE semester IS NULL"))
    connection.execute(sa.text("UPDATE notes n SET author_id = m.owner_id FROM launches l JOIN modules m ON m.id = l.module_id WHERE n.launch_id = l.id AND n.author_id IS NULL"))

    columns = _columns(connection, 'materials')
    if {'storage_key', 'original_filename'}.issubset(columns):
        from core.config import settings
        conflict = connection.scalar(sa.text("""
            SELECT mat.storage_key FROM materials mat
            JOIN launches l ON l.id = mat.launch_id JOIN modules m ON m.id = l.module_id
            WHERE mat.stored_file_id IS NULL GROUP BY mat.storage_key
            HAVING count(DISTINCT m.owner_id) > 1 OR count(DISTINCT mat.original_filename) > 1
            LIMIT 1
        """))
        if conflict is not None:
            raise RuntimeError('У одного старого файла разные владельцы или имена. Нужна проверка перед переносом; данные не удалены')
        connection.execute(sa.text('''
            INSERT INTO stored_files (bucket, storage_key, original_filename, mime_type, size_bytes, uploaded_by_id, created_at)
            SELECT :bucket, mat.storage_key, min(mat.original_filename),
                CASE lower(substring(min(mat.original_filename) from '\\.[^.]+$'))
                    WHEN '.txt' THEN 'text/plain' WHEN '.csv' THEN 'text/csv'
                    WHEN '.png' THEN 'image/png' WHEN '.jpg' THEN 'image/jpeg' WHEN '.jpeg' THEN 'image/jpeg'
                    WHEN '.pdf' THEN 'application/pdf'
                    WHEN '.docx' THEN 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                    WHEN '.xlsx' THEN 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    WHEN '.pptx' THEN 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    ELSE 'application/octet-stream' END,
                0, min(m.owner_id), min(mat.created_at)
            FROM materials mat JOIN launches l ON l.id = mat.launch_id JOIN modules m ON m.id = l.module_id
            WHERE mat.stored_file_id IS NULL GROUP BY mat.storage_key
            ON CONFLICT (bucket, storage_key) DO NOTHING
        '''), {'bucket': settings.S3_BUCKET})
        connection.execute(sa.text('''
            UPDATE materials mat SET stored_file_id = f.id FROM stored_files f
            WHERE mat.stored_file_id IS NULL AND f.bucket = :bucket AND f.storage_key = mat.storage_key
        '''), {'bucket': settings.S3_BUCKET})
        op.drop_column('materials', 'storage_key')
        op.drop_column('materials', 'original_filename')


def _normalize_constraints(connection, metadata):
    quote = connection.dialect.identifier_preparer.quote
    for table in metadata.sorted_tables:
        existing = sa.inspect(connection).get_unique_constraints(table.name)
        for constraint in table.constraints:
            if not isinstance(constraint, sa.UniqueConstraint):
                continue
            columns = [column.name for column in constraint.columns]
            match = next((item for item in existing if item['column_names'] == columns), None)
            if match is None:
                op.create_unique_constraint(constraint.name, table.name, columns)
            elif constraint.name and match['name'] != constraint.name:
                connection.execute(sa.text(f'ALTER TABLE {quote(table.name)} RENAME CONSTRAINT {quote(match["name"])} TO {quote(constraint.name)}'))

    for table in metadata.sorted_tables:
        existing = sa.inspect(connection).get_foreign_keys(table.name)
        for constraint in table.foreign_key_constraints:
            columns = [column.name for column in constraint.columns]
            target_columns = [element.column.name for element in constraint.elements]
            matches = [item for item in existing if item['constrained_columns'] == columns]
            valid = len(matches) == 1 and matches[0]['referred_table'] == constraint.referred_table.name and matches[0]['referred_columns'] == target_columns and matches[0].get('options', {}).get('ondelete', '').upper() == (constraint.ondelete or '').upper()
            if valid:
                if constraint.name and matches[0]['name'] != constraint.name:
                    connection.execute(sa.text(f'ALTER TABLE {quote(table.name)} RENAME CONSTRAINT {quote(matches[0]["name"])} TO {quote(constraint.name)}'))
                continue
            for match in matches:
                op.drop_constraint(match['name'], table.name, type_='foreignkey')
            op.create_foreign_key(constraint.name, table.name, constraint.referred_table.name, columns, target_columns, ondelete=constraint.ondelete)

        checks = {item['name'] for item in sa.inspect(connection).get_check_constraints(table.name)}
        for constraint in table.constraints:
            if isinstance(constraint, sa.CheckConstraint) and constraint.name not in checks:
                op.create_check_constraint(constraint.name, table.name, constraint.sqltext)

        indexes = {index.name: index for index in table.indexes}
        existing_indexes = sa.inspect(connection).get_indexes(table.name)
        for item in existing_indexes:
            if item.get('duplicates_constraint'):
                continue
            desired = indexes.get(item['name'])
            if desired is None or item['column_names'] != [column.name for column in desired.columns] or item['unique'] != desired.unique:
                op.drop_index(item['name'], table_name=table.name)
        present = {item['name'] for item in sa.inspect(connection).get_indexes(table.name)}
        for name, index in indexes.items():
            if name not in present:
                op.create_index(name, table.name, [column.name for column in index.columns], unique=index.unique)


def upgrade():
    connection = op.get_bind()
    metadata = _schema()
    if connection.dialect.name != 'postgresql':
        raise RuntimeError('Миграции проекта предназначены для PostgreSQL')
    tables = set(sa.inspect(connection).get_table_names())
    if not tables.intersection(metadata.tables):
        metadata.create_all(connection)
        return
    for table in metadata.sorted_tables:
        for column in table.columns:
            if isinstance(column.type, sa.Enum):
                column.type.create(connection, checkfirst=True)
    _prepare_existing(connection, metadata)
    for table in metadata.sorted_tables:
        for column in table.columns:
            if column.primary_key:
                continue
            op.alter_column(table.name, column.name, type_=column.type, nullable=column.nullable, server_default=column.server_default)
    _normalize_constraints(connection, metadata)


def downgrade():
    raise RuntimeError('Начальная миграция принимает существующие данные. Автоматический откат до пустой схемы удалил бы их и не поддерживается')
