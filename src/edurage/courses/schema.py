"""Pydantic models for EduRAG course packs."""

from __future__ import annotations

import warnings

from pydantic import BaseModel, ConfigDict, Field


class CoursePackModel(BaseModel):
    """Base model that rejects fields outside the course-pack contract."""

    model_config = ConfigDict(extra="forbid")


class ParserConfig(CoursePackModel):
    """A document modality parser declaration."""

    type: str
    handler: str


with warnings.catch_warnings():
    warnings.filterwarnings(
        "ignore",
        message=(
            'Field name "schema" in "KnowledgeGraphConfig" '
            'shadows an attribute in parent "CoursePackModel"'
        ),
        category=UserWarning,
    )

    class KnowledgeGraphConfig(CoursePackModel):
        """Knowledge graph schema and vocabulary declaration."""

        schema: str
        entities: list[str]
        relations: list[str]


class ToolConfig(CoursePackModel):
    """An external or Python tool exposed by a course pack."""

    name: str
    type: str
    endpoint: str | None = None
    module: str | None = None


class RetrievalConfig(CoursePackModel):
    """Per-modality retrieval defaults for a course pack."""

    text_weight: float = Field(ge=0.0, le=1.0)
    table_weight: float = Field(ge=0.0, le=1.0)
    image_weight: float = Field(ge=0.0, le=1.0)
    code_weight: float = Field(ge=0.0, le=1.0)
    rerank: bool
    hybrid_search: bool


class CourseDefinition(CoursePackModel):
    """The course-specific section of a course pack."""

    name: str
    code: str
    description: str
    parsers: list[ParserConfig]
    knowledge_graph: KnowledgeGraphConfig
    tools: list[ToolConfig]
    retrieval_config: RetrievalConfig


class CoursePack(CoursePackModel):
    """Root course-pack document."""

    course_pack: CourseDefinition