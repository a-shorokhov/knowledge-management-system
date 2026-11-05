from sqlalchemy import select

from models.ai_retrospectives import AIRetrospective
from models.launch_designs import LaunchDesign
from models.launch_reflections import LaunchReflection
from models.launches import Launch
from models.materials import Material
from models.modules import Module
from models.notes import Note
from models.stored_files import StoredFile
from repositories.launch_designs import LaunchDesignRepository
from repositories.launch_reflections import LaunchReflectionRepository
from repositories.launches import LaunchRepository
from repositories.notes import NoteRepository
from repositories.transactions import transaction


class AIRetrospectiveRepository:
    def __init__(self, db):
        self.db = db

    def _owned_launch(self, launch_id, user_id):
        return select(Launch).join(Module, Module.id == Launch.module_id).where(
            Launch.id == launch_id, Module.owner_id == user_id)

    @staticmethod
    def _to_dict(report):
        return {key: getattr(report, key) for key in (
            'id', 'launch_id', 'compared_to_launch_id', 'generated_by_id', 'content', 'created_at')}

    def get_context(self, launch_id, user_id):
        launch = self.db.scalar(self._owned_launch(launch_id, user_id))
        if launch is None:
            return None
        design = self.db.get(LaunchDesign, launch_id)
        reflection = self.db.get(LaunchReflection, launch_id)
        notes = self.db.scalars(select(Note).where(Note.launch_id == launch_id).order_by(Note.id).limit(201)).all()
        materials = self.db.execute(select(
            Material.id, Material.title, Material.description, Material.kind, Material.stored_file_id,
            StoredFile.original_filename, StoredFile.indexing_status, StoredFile.deletion_pending,
        ).join(StoredFile, StoredFile.id == Material.stored_file_id).where(
            Material.launch_id == launch_id).order_by(Material.id).limit(201)).mappings().all()
        return {'launch': LaunchRepository._to_dict(launch),
                'design': LaunchDesignRepository._to_dict(design) if design else None,
                'reflection': LaunchReflectionRepository._to_dict(reflection) if reflection else None,
                'notes': [NoteRepository._to_dict(note) for note in notes],
                'materials': [dict(row) for row in materials]}

    def finish_read(self):
        self.db.rollback()

    def save_report(self, user_id, module_id, launch_id, compared_to_launch_id, content):
        with transaction(self.db):
            module = self.db.scalar(select(Module).where(
                Module.id == module_id, Module.owner_id == user_id).with_for_update())
            if module is None:
                return None
            ids = [launch_id] if compared_to_launch_id is None else [launch_id, compared_to_launch_id]
            launches = self.db.scalars(select(Launch).where(
                Launch.id.in_(ids), Launch.module_id == module_id).order_by(Launch.id).with_for_update()).all()
            if len(launches) != len(ids):
                return None
            report = AIRetrospective(launch_id=launch_id, compared_to_launch_id=compared_to_launch_id,
                                     generated_by_id=user_id, content=content)
            self.db.add(report)
            self.db.flush()
            self.db.refresh(report)
            result = self._to_dict(report)
        return result

    def get_history(self, launch_id, user_id, limit, offset):
        if self.db.scalar(self._owned_launch(launch_id, user_id)) is None:
            return None
        rows = self.db.scalars(select(AIRetrospective).where(AIRetrospective.launch_id == launch_id).order_by(
            AIRetrospective.created_at.desc(), AIRetrospective.id.desc()).limit(limit).offset(offset)).all()
        return [self._to_dict(row) for row in rows]
