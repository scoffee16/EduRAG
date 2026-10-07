from pathlib import Path

from edurage.core.config import Settings


def _read_environment_keys(path: Path) -> set[str]:
    keys: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        key, separator, _ = line.partition("=")
        assert separator, f"Invalid environment entry: {raw_line!r}"
        keys.add(key)
    return keys


def test_env_example_matches_settings_fields(project_root: Path) -> None:
    environment_keys = _read_environment_keys(project_root / ".env.example")
    settings_keys = {
        f"EDURAGE_{field_name.upper()}" for field_name in Settings.model_fields
    }

    assert len(environment_keys) == 17
    assert len(settings_keys) == 17
    assert environment_keys == settings_keys
