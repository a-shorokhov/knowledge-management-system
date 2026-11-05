from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def omit_draft_defaults(schema):
    # Missing fields are absent from the document, not implicit null values.
    for field in schema.get("properties", {}).values():
        field.pop("default", None)


class DraftFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, json_schema_extra=omit_draft_defaults)


class DesignPassport(DraftFields):
    category: str = Field(default=None, description="Категория образовательного модуля")
    module_type: Literal["project", "non_project", "mixed"] = Field(default=None, description="Проектный, непроектный или смешанный модуль")
    annotation: str = Field(default=None, description="Краткое описание содержания")
    target_audience: str = Field(default=None, description="Для кого предназначен модуль")
    duration_weeks: int = Field(default=None, gt=0, le=2147483647, description="Продолжительность в неделях, положительное целое")
    duration_academic_hours: int = Field(default=None, gt=0, le=2147483647, description="Объём в академических часах, положительное целое")
    delivery_format: Literal["offline", "online", "mixed"] = Field(default=None, description="Очный, дистанционный или смешанный формат")
    language: str = Field(default=None, description="Язык обучения")
    planned_capacity: int = Field(default=None, ge=0, le=2147483647, description="Плановая вместимость; не фактическое число участников запуска")


class EducationalConcept(DraftFields):
    relevance: str = Field(default=None, description="Актуальность модуля")
    goal: str = Field(default=None, description="Образовательная цель")
    learning_outcomes: list[str] = Field(default=None, description="Результаты обучения в заданном автором порядке, без ограничения количества")
    prerequisites: str = Field(default=None, description="Требования к предварительной подготовке")
    success_criteria: str = Field(default=None, description="Критерии успешного освоения")


class ProjectStage(DraftFields):
    position: int = Field(default=None, ge=0, le=2147483647, description="Неотрицательная позиция этапа; порядок массива сохраняется без сортировки")
    student_activity: str = Field(default=None, description="Деятельность обучающихся на этапе")
    intermediate_result: str = Field(default=None, description="Промежуточный результат этапа")


class DesignProject(DraftFields):
    task: str = Field(default=None, description="Проектная задача")
    context: str = Field(default=None, description="Контекст выполнения проекта")
    partner: str | None = Field(default=None, description="Партнёр проекта; допускается null")
    expected_output: str = Field(default=None, description="Ожидаемый продукт проекта")
    work_format: Literal["individual", "team", "mixed"] = Field(default=None, description="Индивидуальная, командная или смешанная работа")
    stages: list[ProjectStage] = Field(default=None, description="Этапы проекта в порядке автора, без ограничения количества")


class LaunchDesignData(DraftFields):
    passport: DesignPassport = Field(default=None, description="Дополнительные поля паспорта, без дублирования названий и идентификаторов")
    educational_concept: EducationalConcept = Field(default=None, description="Образовательный замысел")
    project: DesignProject = Field(default=None, description="Описание проекта")


class ReplaceLaunchDesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_version: int = Field(default=1, gt=0, strict=True, description="Поддерживается только версия 1")
    data: LaunchDesignData = Field(default_factory=LaunchDesignData, description="Полная замена документа; отсутствующие поля удаляются. Пустой объект очищает заполнение")

    @field_validator("template_version")
    @classmethod
    def supported_version(cls, value):
        if value != 1:
            raise ValueError("Поддерживается только версия шаблона 1")
        return value


class LaunchDesignResponse(BaseModel):
    launch_id: int
    template_version: int
    data: LaunchDesignData
    created_at: datetime | None
    updated_at: datetime | None
