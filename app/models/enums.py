from enum import Enum


class RunStatus(str, Enum):
    draft = "draft"
    active = "active"
    completed = "completed"


class MaterialKind(str, Enum):
    plan = "plan"
    presentation = "presentation"
    assignment = "assignment"
    reading = "reading"
    feedback = "feedback"
    other = "other"


class FileIndexStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class NotePriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class NoteStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    done = "done"
