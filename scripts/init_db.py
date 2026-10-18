"""Create tables, apply additive migrations and sync course packs idempotently."""

from edurage.core.config import get_settings
from edurage.courses.sync import sync_course_packs_from_settings
from edurage.db.engine import get_engine
from edurage.db.migrations import ensure_schema
from edurage.db.models import Base


def main() -> None:
    settings = get_settings()
    engine = get_engine(settings.postgres_dsn)
    Base.metadata.create_all(engine)
    applied = ensure_schema(engine)
    counts = sync_course_packs_from_settings(settings)

    print("Database schema initialized.")
    if applied:
        print("Applied migrations: " + ", ".join(applied))
    print(
        "Course packs synchronized: "
        f"created={counts['created']} updated={counts['updated']} "
        f"unchanged={counts['unchanged']} skipped={counts['skipped']} "
        f"total={counts['total']}"
    )


if __name__ == "__main__":
    main()
