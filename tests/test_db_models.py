from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from edurage.db.models import Base, Chunk, CoursePack, Document


def test_model_columns_and_constraints() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert {column["name"] for column in inspector.get_columns("course_packs")} >= {
        "id",
        "name",
        "code",
        "origin",
        "config",
        "created_at",
    }
    assert {column["name"] for column in inspector.get_columns("documents")} >= {
        "id",
        "course_id",
        "filename",
        "file_type",
        "storage_path",
        "metadata",
    }
    assert {column["name"] for column in inspector.get_columns("chunks")} >= {
        "id",
        "document_id",
        "content",
        "modality",
        "embedding",
        "metadata",
    }
    assert inspector.get_unique_constraints("course_packs")[0]["column_names"] == ["code"]


def test_model_relationships_and_required_fields() -> None:
    course = CoursePack(name="Computer Organization", code="CS-CO", config={})
    document = Document(
        course_pack=course,
        filename="guide.pdf",
        file_type="pdf",
        storage_path="docs/guide.pdf",
        document_metadata={},
    )
    chunk = Chunk(
        document=document,
        content="A chunk",
        modality="text",
        embedding=[0.1, 0.2],
        chunk_metadata={"page": 1},
    )
    assert document.course_pack is course
    assert chunk.document is document
    assert course.documents == [document]
    assert document.chunks == [chunk]


def test_models_persist_with_sqlite() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        course = CoursePack(name="Course", code="COURSE", config={})
        session.add(course)
        session.flush()
        session.add(
            Document(
                course_id=course.id,
                filename="file.pdf",
                file_type="pdf",
                storage_path="file.pdf",
                document_metadata={},
            )
        )
        session.commit()
        assert session.query(Document).count() == 1
