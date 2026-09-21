"""Single source of the package version.

Kept in its own module so ``caged.client`` can read it for the User-Agent
header without importing ``caged`` and creating a cycle, and so
``pyproject.toml`` can read it through ``[tool.hatch.version]`` rather than
declaring the number a second time. 0.2.0 was published with a User-Agent
that said 0.1.0 in the TypeScript client for exactly that reason: a version
written down twice is a version that disagrees with itself.
"""

__version__ = "0.3.0"
