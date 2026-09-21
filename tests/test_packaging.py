"""Guards on what this package claims to be, and on its own CI.

This repository is the one `pip install caged-sdk` installs. Two ways that
has gone wrong before: a version written down twice (the npm sibling
published 0.2.0 with a User-Agent announcing 0.1.0), and a test step that
could not fail (`pytest tests/ -v || true`, against no tests/ directory).
Both are asserted here rather than remembered.
"""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # 3.10 is the floor in requires-python; tomllib is stdlib only from 3.11.
    import tomli as tomllib

from caged._version import __version__

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
CI = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_publishes_under_the_name_users_install() -> None:
    # PyPI's "caged" belongs to an unrelated Brazilian labour-statistics
    # project. The import name is still `caged`, which is why installing the
    # wrong one looks fine until the first call.
    assert CONFIG["project"]["name"] == "caged-sdk"


def test_version_is_single_sourced() -> None:
    assert "version" in CONFIG["project"]["dynamic"]
    assert "version" not in CONFIG["project"]
    assert CONFIG["tool"]["hatch"]["version"]["path"] == "caged/_version.py"
    assert __version__


def test_the_websocket_dependency_is_declared() -> None:
    # caged.terminal, caged.stream and caged.mcp import it at module scope,
    # so `import caged` fails without it.
    assert any(dep.startswith("websockets") for dep in CONFIG["project"]["dependencies"])


def test_the_test_step_can_fail() -> None:
    lines = [
        line.strip()
        for line in CI.splitlines()
        if "pytest" in line and not line.lstrip().startswith("#")
    ]
    assert lines, "CI does not run pytest"
    for line in lines:
        assert "|| true" not in line, line


def test_ci_runs_the_type_checker_in_strict_mode() -> None:
    assert CONFIG["tool"]["mypy"]["strict"] is True
    assert any(
        "mypy" in line and not line.lstrip().startswith("#") for line in CI.splitlines()
    )


def test_the_python_floor_and_the_ci_matrix_agree() -> None:
    floor = CONFIG["project"]["requires-python"]
    assert floor.startswith(">=")
    lowest = floor.removeprefix(">=").strip()
    assert f"'{lowest}'" in CI, f"CI does not test the declared floor {lowest}"
