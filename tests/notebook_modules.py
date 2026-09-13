"""Import a module out of ``notebooks/<source>/`` under a unique name.

Notebook directories are not packages, so tests reach them by putting the
directory on ``sys.path`` and importing by bare name. That breaks as soon as
two sources use the same filename: ``notebooks/cdc/utils/fetch.py`` and
``notebooks/voteview/fetch.py`` both want to be ``fetch``, and the first one
imported wins ``sys.modules`` for the whole session. The second test file then
runs against the wrong module and fails with ``AttributeError`` -- and only
when the suite runs in that order, so it passes in isolation.

Loading by path under a qualified name avoids it. Where the modules live in a
real package -- ``notebooks/cdc/utils/`` -- the package is registered first so
that its ``from . import sibling`` statements resolve.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

NOTEBOOKS = Path(__file__).resolve().parents[1] / "notebooks"


def _register(name: str, path: Path, package: str | None = None) -> ModuleType:
    """Load ``path`` as ``name``, as a package if it is an ``__init__.py``."""
    if name in sys.modules:
        return sys.modules[name]
    is_package = path.name == "__init__.py"
    spec = importlib.util.spec_from_file_location(
        name, path, submodule_search_locations=[str(path.parent)] if is_package else None)
    if spec is None or spec.loader is None:            # pragma: no cover
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    if package:
        module.__package__ = package
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load(source: str, module: str) -> ModuleType:
    """Import ``notebooks/<source>/<module>.py`` under a name unique to *source*.

    *source* may name a subdirectory -- ``load("cdc/utils", "fetch")`` -- since
    a source's modules can live in a package rather than beside the notebooks.
    """
    directory = NOTEBOOKS.joinpath(*source.split("/"))
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    # the repo root, for modules that import mcp_server or db_import
    root = str(NOTEBOOKS.parent)
    if root not in sys.path:
        sys.path.insert(0, root)

    package = source.replace("/", "_")
    init = directory / "__init__.py"
    if init.exists():
        _register(package, init)
        return _register(f"{package}.{module}", directory / f"{module}.py", package=package)
    return _register(f"{package}_{module}", directory / f"{module}.py")
