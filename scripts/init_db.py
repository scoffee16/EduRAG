"""Create all relational tables idempotently."""

from edurage.db.engine import get_engine
from edurage.db.models import Base


def main() -> None:
    Base.metadata.create_all(get_engine())
    print("Database schema initialized.")


if __name__ == "__main__":
    main()
