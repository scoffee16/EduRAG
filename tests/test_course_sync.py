"""Course-pack synchronization tests over an isolated SQLite database."""

from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from edurage.core.config import Settings
from edurage.courses.loader import load_course_pack
from edurage.courses.sync import (
    locate_configs_dir,
    sync_course_packs,
    sync_course_packs_from_settings,
)
from edurage.db.models import Base, CoursePack


def _payload(*, code: str, name: str, description: str = "课程描述") -> dict:
    return {
        "course_pack": {
            "name": name,
            "code": code,
            "description": description,
            "parsers": [{"type": "pdf", "handler": "mineru"}],
            "knowledge_graph": {
                "schema": "comp_org_schema.json",
                "entities": ["Instruction", "ALU"],
                "relations": ["instruction_has_microsequence"],
            },
            "tools": [
                {
                    "name": "vhdl_simulator",
                    "type": "python",
                    "module": "edurage.tools.vhdl",
                }
            ],
            "retrieval_config": {
                "text_weight": 0.4,
                "table_weight": 0.2,
                "image_weight": 0.2,
                "code_weight": 0.2,
                "rerank": True,
                "hybrid_search": True,
            },
        }
    }


def _write_pack(path: Path, payload: dict) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _course_pack_files(tmp_path: Path) -> Path:
    packs_dir = tmp_path / "configs" / "course_packs"
    packs_dir.mkdir(parents=True)
    return packs_dir


def test_sync_creates_course_packs_and_is_idempotent(tmp_path: Path) -> None:
    packs_dir = _course_pack_files(tmp_path)
    _write_pack(packs_dir / "comp_org.yaml", _payload(code="CS-COMP-ORG", name="计算机组成原理"))
    _write_pack(packs_dir / "algo.yaml", _payload(code="cs-algo", name="算法设计与分析"))
    (packs_dir / "broken.yaml").write_text("course_pack: [\n", encoding="utf-8")
    (packs_dir / "notes.txt").write_text("ignored", encoding="utf-8")

    factory = _session_factory()
    configs_dir = tmp_path / "configs"

    first = sync_course_packs(factory, configs_dir)
    assert first == {"created": 2, "updated": 0, "unchanged": 0, "skipped": 1, "total": 2}

    second = sync_course_packs(factory, configs_dir)
    assert second == {"created": 0, "updated": 0, "unchanged": 2, "skipped": 1, "total": 2}

    with factory() as session:
        rows = session.scalars(select(CoursePack).order_by(CoursePack.code)).all()
        assert [row.code for row in rows] == ["CS-ALGO", "CS-COMP-ORG"]
        comp_org = rows[1]
        assert comp_org.name == "计算机组成原理"
        assert comp_org.description == "课程描述"
        assert comp_org.updated_at is not None
        assert set(comp_org.config) == {
            "parsers",
            "knowledge_graph",
            "tools",
            "retrieval_config",
        }
        assert comp_org.config["knowledge_graph"]["schema"] == "comp_org_schema.json"
        assert comp_org.config["retrieval_config"]["text_weight"] == 0.4
        assert "course_pack" not in comp_org.config


def test_sync_updates_changed_course_pack(tmp_path: Path) -> None:
    packs_dir = _course_pack_files(tmp_path)
    pack_path = packs_dir / "comp_org.yaml"
    _write_pack(pack_path, _payload(code="CS-COMP-ORG", name="旧课程名", description="旧描述"))

    factory = _session_factory()
    configs_dir = tmp_path / "configs"
    assert sync_course_packs(factory, configs_dir)["created"] == 1

    _write_pack(pack_path, _payload(code="CS-COMP-ORG", name="新课程名", description="新描述"))
    updated = sync_course_packs(factory, configs_dir)
    assert updated == {"created": 0, "updated": 1, "unchanged": 0, "skipped": 0, "total": 1}

    with factory() as session:
        pack = session.scalars(select(CoursePack)).one()
        assert pack.name == "新课程名"
        assert pack.description == "新描述"


def test_sync_accepts_course_packs_directory_directly(tmp_path: Path) -> None:
    packs_dir = _course_pack_files(tmp_path)
    _write_pack(packs_dir / "comp_org.yaml", _payload(code="CS-COMP-ORG", name="计算机组成原理"))

    factory = _session_factory()
    counts = sync_course_packs(factory, packs_dir)

    assert counts["created"] == 1
    with factory() as session:
        assert session.scalars(select(CoursePack)).one().code == "CS-COMP-ORG"


def test_sync_from_settings_uses_repository_configs() -> None:
    settings = Settings()
    located = locate_configs_dir(settings)
    assert located is not None
    assert (located / "course_packs" / "comp_org.yaml").is_file()

    factory = _session_factory()
    counts = sync_course_packs_from_settings(settings, session_factory=factory)
    assert counts["created"] >= 1
    assert counts["skipped"] == 0

    definition = load_course_pack(located / "course_packs" / "comp_org.yaml").course_pack
    with factory() as session:
        pack = session.scalars(
            select(CoursePack).where(CoursePack.code == definition.code.strip().upper())
        ).one()
        assert pack.name == definition.name
        assert pack.description == definition.description
        assert pack.config["retrieval_config"]["text_weight"] == 0.4
        assert pack.config["knowledge_graph"]["schema"] == "comp_org_schema.json"
        assert pack.updated_at is not None


def test_sync_reports_missing_configs_directory(tmp_path: Path) -> None:
    factory = _session_factory()
    counts = sync_course_packs(factory, tmp_path / "missing")

    assert counts == {"created": 0, "updated": 0, "unchanged": 0, "skipped": 0, "total": 0}
