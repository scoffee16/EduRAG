"""Load and validate EduRAG course-pack YAML files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from edurage.courses.schema import CoursePack


def _yaml_validation_error(path: Path, detail: str) -> ValidationError:
    message = f"Invalid course pack YAML at {path}: {detail}"
    return ValidationError.from_exception_data(
        title="CoursePack",
        line_errors=[
            {
                "type": "value_error",
                "loc": (),
                "msg": message,
                "input": str(path),
                "ctx": {"error": ValueError(message)},
            }
        ],
    )


def load_course_pack(path: str | Path) -> CoursePack:
    """Read, parse, and validate a course pack from a YAML file."""

    source = Path(path)
    try:
        raw: Any = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise _yaml_validation_error(source, str(exc)) from exc

    return CoursePack.model_validate(raw)
