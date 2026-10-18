from pathlib import Path

import pytest
from pydantic import ValidationError

from edurage.courses.loader import load_course_pack


def test_complete_course_pack_is_loaded(configs_dir: Path) -> None:
    course_pack = load_course_pack(configs_dir / "course_packs" / "comp_org.yaml")
    definition = course_pack.course_pack

    assert definition.code == "CS-COMP-ORG"
    assert definition.name == "示例课程 · 计算机组成原理"
    assert definition.name.startswith("示例课程")
    assert "不能删除" in definition.description

    assert [parser.type for parser in definition.parsers] == [
        "pdf",
        "pptx",
        "image",
        "vhdl",
        "waveform",
    ]
    assert [tool.name for tool in definition.tools] == [
        "vhdl_simulator",
        "waveform_checker",
        "microprogram_generator",
    ]
    assert definition.knowledge_graph.entities == [
        "Instruction",
        "MicroAddress",
        "ControlSignal",
        "Register",
        "ALU",
        "BranchCondition",
    ]
    assert definition.knowledge_graph.relations == [
        "instruction_has_microsequence",
        "microaddress_emits_signal",
        "branch_condition_determines_next",
        "signal_controls_component",
    ]
    assert len(definition.parsers) == 5
    assert len(definition.tools) == 3
    assert len(definition.knowledge_graph.entities) == 6
    assert len(definition.knowledge_graph.relations) == 4


def test_invalid_yaml_raises_validation_error(tmp_path: Path) -> None:
    invalid_course_pack = tmp_path / "invalid_course_pack.yaml"
    invalid_course_pack.write_text("course_pack: [\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        load_course_pack(invalid_course_pack)
