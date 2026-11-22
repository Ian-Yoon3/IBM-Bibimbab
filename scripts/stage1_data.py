"""The stage 1 worlds (hand-written receipt dates of PO01) are kept as a test
fixture; this module rebuilds the stage 1 data set for the stage 1 tests and
for replaying the 2026-11-12 sweep.
"""

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

import engine.loader
import engine.tools

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPO_DATA = _REPO_ROOT / "data"
_STAGE1_WORLDS = _REPO_ROOT / "tests" / "fixtures" / "stage1_worlds.csv"


def make_stage1_data_dir(dest) -> Path:
    """Copy the repository's data/ folder to *dest*, remove causes.csv from the
    copy, and place tests/fixtures/stage1_worlds.csv there as worlds.csv.

    Returns the destination path as a :class:`pathlib.Path`.  Never writes into
    the repository's data/.
    """
    dest = Path(dest)
    if dest.resolve() == _REPO_DATA.resolve():
        raise ValueError("dest must not be the repository data/ directory")
    shutil.copytree(_REPO_DATA, dest, dirs_exist_ok=True)
    causes = dest / "causes.csv"
    if causes.exists():
        causes.unlink()
    shutil.copy2(_STAGE1_WORLDS, dest / "worlds.csv")
    return dest


@contextmanager
def use_stage1_default_data():
    """Context manager that redirects the engine default data directory to a
    temporary stage 1 data folder for the duration of the ``with`` block.

    On entry:
      - creates a temporary directory and builds the stage 1 data set there
        with :func:`make_stage1_data_dir`;
      - sets ``engine.loader._DEFAULT_DATA_DIR`` to that directory;
      - clears ``engine.tools._DB_CACHE`` so the next call loads fresh data.

    On exit:
      - restores ``engine.loader._DEFAULT_DATA_DIR`` to its previous value;
      - clears ``engine.tools._DB_CACHE`` again;
      - removes the temporary directory.
    """
    prev = engine.loader._DEFAULT_DATA_DIR
    with tempfile.TemporaryDirectory() as _tmpdir:
        stage1_dir = make_stage1_data_dir(Path(_tmpdir) / "data")
        engine.loader._DEFAULT_DATA_DIR = stage1_dir
        engine.tools._DB_CACHE.clear()
        try:
            yield stage1_dir
        finally:
            engine.loader._DEFAULT_DATA_DIR = prev
            engine.tools._DB_CACHE.clear()
