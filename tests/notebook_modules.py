"""Import a module out of ``notebooks/<source>/`` under a unique name.

Notebook directories are not packages, so tests reach them by putting the
directory on ``sys.path`` and importing by bare name. That breaks as soon as
two sources use the same filename: ``notebooks/cdc/fetch.py`` and
``notebooks/voteview/fetch.py`` both want to be ``fetch``, and the first one
imported wins ``sys.modules`` for the whole session. The second test file then
runs against the wrong module and fails with ``AttributeError`` -- and only
when the suite runs in that order, so it passes in isolation.

``utils.py`` exists in five source directories and is the same accident
waiting to happen.

Loading by path under a qualified name avoids it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

NOTEBOOKS = Path(__file__).resolve().parents[1] / "notebooks"


def load(source: str, module: str) -> ModuleType:
    """Import ``notebooks/<source>/<module>.py`` as ``<source>_<module>``.

    The source directory goes on ``sys.path`` as well, since these modules
    import their siblings by bare name.
    """
    directory = NOTEBOOKS / source
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))

    qualified = f"{source}_{module}"
    if qualified in sys.modules:
        return sys.modules[qualified]

    spec = importlib.util.spec_from_file_location(qualified, directory / f"{module}.py")
    if spec is None or spec.loader is None:               # pragma: no cover
        raise ImportError(f"cannot load {directory / (module + '.py')}")
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = loaded
    spec.loader.exec_module(loaded)
    return loaded
