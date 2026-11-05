from sqlalchemy import func, select

from models.document_chunks import DocumentChunk
from models.enums import FileIndexStatus
from models.launches import Launch
from models.materials import Material
from models.modules import Module
from models.stored_files import StoredFile


class RagRepository:
    def __init__(self, db):
        self.db = db

    def has_scope(self, user_id, module_id, launch_id):
        statement = select(Module.id).where(Module.id == module_id, Module.owner_id == user_id)
        if launch_id is not None:
            statement = statement.join(Launch, Launch.module_id == Module.id).where(Launch.id == launch_id)
        return self.db.scalar(statement) is not None

    def search(self, user_id, module_id, launch_id, embedding):
        allowed = select(Material.stored_file_id, func.min(Material.id).label('material_id')).join(
            Launch, Launch.id == Material.launch_id).join(Module, Module.id == Launch.module_id).where(
                Module.id == module_id, Module.owner_id == user_id)
        if launch_id is not None:
            allowed = allowed.where(Launch.id == launch_id)
        allowed = allowed.group_by(Material.stored_file_id).cte('allowed_files')
        statement = select(
            DocumentChunk.id.label('chunk_id'), DocumentChunk.chunk_index, DocumentChunk.content,
            DocumentChunk.page_number, DocumentChunk.slide_number, DocumentChunk.sheet_name, DocumentChunk.cell_range,
            Material.id.label('material_id'), Material.title, Launch.id.label('launch_id'), Launch.year,
        ).join(allowed, allowed.c.stored_file_id == DocumentChunk.stored_file_id).join(
            StoredFile, StoredFile.id == DocumentChunk.stored_file_id).join(
            Material, Material.id == allowed.c.material_id).join(Launch, Launch.id == Material.launch_id).where(
                StoredFile.indexing_status == FileIndexStatus.ready, StoredFile.deletion_pending.is_(False),
                DocumentChunk.embedding.is_not(None),
        ).order_by(DocumentChunk.embedding.cosine_distance(embedding), DocumentChunk.id).limit(5)
        return [dict(row) for row in self.db.execute(statement).mappings()]
