"""Tests for release version metadata."""
from __future__ import annotations

import pathlib
import re
import tomllib

from talon_core.constants import APP_VERSION
from talon_core.version import DEFAULT_APP_VERSION, current_app_version


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_release_version_constants_are_aligned() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = pyproject["project"]["version"]

    assert DEFAULT_APP_VERSION == project_version
    assert APP_VERSION == project_version
    assert current_app_version() == project_version

    buildozer_text = (REPO_ROOT / "build" / "buildozer.spec").read_text(
        encoding="utf-8"
    )
    assert f"version = {project_version}" in buildozer_text

    inno_text = (REPO_ROOT / "build" / "talon-desktop-windows.iss").read_text(
        encoding="utf-8"
    )
    match = re.search(r'#define AppVersion "([^"]+)"', inno_text)
    assert match is not None
    assert match.group(1) == project_version
