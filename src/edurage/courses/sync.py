"""Synchronize YAML course-pack definitions into the ``course_packs`` table.

The course metadata in ``configs/course_packs/*.yaml`` is the source of truth.
Synchronization is idempotent: definitions already present are updated in place,
new ones are inserted, and unchanged ones are left untouched so that concurrent
uploads keep working while the API serves course names and descriptions.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from edurage.core.config import Settings, get_settings
from edurage.courses.loader import load_course_pack
from edurage.courses.schema import CourseDefinition
from edurage.db.engine import get_session_factory
from edurage.db.models import CoursePack

logger = logging.getLogger(__name__)

_CONFIGS_DIRNAME = "configs"
_COURSE_PACKS_DIRNAME = "course_packs"
_COURSE_PACK_SUFFIXES = frozenset({".yaml", ".yml"})


def sync_course_packs(
    session_factory: Callable[[], Session],
    configs_dir: str | Path,
) -> dict[str, int]:
    """Upsert every YAML course-pack definition found below ``configs_dir``.

    ``configs_dir`` may be either the repository ``configs`` directory or its
    ``course_packs`` subdirectory. Files that fail to parse are reported and
    skipped instead of aborting the whole synchronization. Returns counters
    ``created``, ``updated``, ``unchanged``, ``skipped`` and ``total``.
    """

    counts = {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "total": 0}
    packs_dir = _resolve_packs_dir(Path(configs_dir))
    if packs_dir is None:
        logger.warning("no course pack definitions found under %s", configs_dir)
        return counts

    files = sorted(
        path
        for path in packs_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _COURSE_PACK_SUFFIXES
    )
    for path in files:
        # A single malformed file must not abort the whole synchronization.
        try:
            pack = load_course_pack(path)
        except Exception as exc:  # noqa: BLE001
            counts["skipped"] += 1
            logger.warning("skipping invalid course pack %s: %s", path, exc)
            continue

        counts["total"] += 1
        with session_factory() as session:
            outcome = _upsert_course_pack(session, pack.course_pack)
            session.commit()
        counts[outcome] += 1
        logger.info("course pack %s %s", pack.course_pack.code, outcome)

    logger.info(
        "course pack synchronization finished: %s",
        ", ".join(f"{name}={value}" for name, value in counts.items()),
    )
    return counts


def sync_course_packs_from_settings(
    settings: Settings | None = None,
    session_factory: Callable[[], Session] | None = None,
) -> dict[str, int]:
    """Locate the configuration directory and synchronize every course pack."""

    resolved_settings = settings or get_settings()
    configs_dir = locate_configs_dir(resolved_settings)
    if configs_dir is None:
        logger.warning("course pack synchronization skipped: configuration directory missing")
        return {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "total": 0}
    factory = session_factory or get_session_factory(resolved_settings)
    return sync_course_packs(factory, configs_dir)


def locate_configs_dir(settings: Settings | None = None) -> Path | None:
    """Find the repository ``configs`` directory in local and container layouts.

    The application is imported either from a source checkout (``src`` layout)
    or from the container image (``/app/src``); walking the ancestors of this
    module therefore covers both. A relative ``./configs`` directory is accepted
    as a last resort for deployments that mount the configuration next to the
    working directory.
    """

    resolved_settings = settings or get_settings()
    candidates: list[Path] = [
        parent / _CONFIGS_DIRNAME for parent in Path(__file__).resolve().parents
    ]
    candidates.append(Path.cwd() / _CONFIGS_DIRNAME)
    for candidate in candidates:
        if _is_configs_dir(candidate):
            logger.debug("using configuration directory %s", candidate)
            return candidate
    logger.warning(
        "course pack configuration directory not found (env=%s, cwd=%s)",
        resolved_settings.env,
        Path.cwd(),
    )
    return None


def _is_configs_dir(candidate: Path) -> bool:
    if not candidate.is_dir():
        return False
    if (candidate / _COURSE_PACKS_DIRNAME).is_dir():
        return True
    return any(candidate.glob("*.yaml"))


def _resolve_packs_dir(configs_dir: Path) -> Path | None:
    if (configs_dir / _COURSE_PACKS_DIRNAME).is_dir():
        return configs_dir / _COURSE_PACKS_DIRNAME
    if configs_dir.is_dir():
        return configs_dir
    return None


def _course_config(definition: CourseDefinition) -> dict[str, object]:
    return {
        "parsers": [parser.model_dump() for parser in definition.parsers],
        "knowledge_graph": definition.knowledge_graph.model_dump(),
        "tools": [tool.model_dump() for tool in definition.tools],
        "retrieval_config": definition.retrieval_config.model_dump(),
    }


def _upsert_course_pack(session: Session, definition: CourseDefinition) -> str:
    """Insert or update one definition; return ``created``/``updated``/``unchanged``."""

    code = _normalize_code(definition.code)
    name = definition.name.strip()
    description = definition.description.strip()
    config = _course_config(definition)

    existing = session.scalars(select(CoursePack).where(CoursePack.code == code)).first()
    if existing is None:
        session.add(
            CoursePack(
                code=code,
                name=name,
                description=description,
                config=config,
                origin="config",
                updated_at=datetime.now(UTC),
            )
        )
        return "created"

    if (
        existing.name == name
        and existing.description == description
        and existing.config == config
        and existing.origin == "config"
    ):
        return "unchanged"

    existing.name = name
    existing.description = description
    existing.config = config
    # The YAML definition is authoritative: a row that shadowed a configured
    # course must be reclaimed as config-managed when the sync owns it again.
    existing.origin = "config"
    existing.updated_at = datetime.now(UTC)
    return "updated"


def _normalize_code(code: str) -> str:
    return code.strip().upper()
