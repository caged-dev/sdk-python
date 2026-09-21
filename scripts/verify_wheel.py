"""Assert that a built wheel carries the repairs, not just the version bump.

Run against the INSTALLED package, from a directory that is not the source
tree::

    python -m build
    python -m venv /tmp/verify && /tmp/verify/bin/pip install dist/*.whl
    /tmp/verify/bin/python scripts/verify_wheel.py 0.3.0

This exists because 0.2.0 was published as a repackage of 0.1.0: the version
number moved, the code did not, and every check in CI looked at the working
tree rather than at the artifact. Checking the source proves nothing about
what `pip install` hands anyone.
"""

from __future__ import annotations

import inspect
import sys


def fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def main(expected_version: str | None) -> None:
    import caged
    from caged.client import _FilesAPI, _SnapshotsAPI

    if expected_version and caged.__version__ != expected_version:
        fail(f"wheel reports {caged.__version__}, expected {expected_version}")

    write = inspect.getsource(_FilesAPI.write)
    if 'params={"path": path}' not in write:
        fail("files.write does not send the path in the query string")
    if '"content": content' not in write:
        fail("files.write does not send the content in the body")

    if "_request_text" not in inspect.getsource(_FilesAPI.read):
        fail("files.read still parses a text/plain body as JSON")

    if "target_sandbox_id" not in inspect.getsource(_SnapshotsAPI.restore):
        fail("snapshots.restore does not send target_sandbox_id")

    for name in ("CagedPlanLimitError", "CagedNotFoundError", "CagedValidationError"):
        if not hasattr(caged, name):
            fail(f"{name} is missing from the installed package")

    # The User-Agent is built from the version rather than written out again.
    source = inspect.getsource(caged.client)
    if "caged-python/{__version__}" not in source:
        fail("the User-Agent header is not derived from the package version")

    print(f"ok: installed caged-sdk {caged.__version__} carries the repairs")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
