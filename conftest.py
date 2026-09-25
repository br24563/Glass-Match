"""Make the repository root importable however pytest is invoked.

The `pytest` console script does not put the current working directory on
``sys.path`` (unlike ``python -m pytest``). On Linux CI that made every
``import glassmatch`` fail at collection: 12 collection errors and exit code 2
in about a second, while the same command passed on Windows. Relying on the
invocation directory is a portability trap, so the root is added explicitly here.
"""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parent)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
