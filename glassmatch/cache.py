"""Local derived-data cache: Parquet copies of the database and its summaries.

The CSVs in data/normalized stay the source of truth (reviewable, diffable,
pinned by MANIFEST.json). Parsing ~30 MB of CSV and recomputing the summary,
line indices and validation report cost most of a cold start, so the first
load writes them as Parquet / JSON to a per-user cache directory and later
loads read those instead.

The cache key covers everything that could change the answer: the package
version, the manifest's data version and every CSV's name, size and mtime. A
changed file, a new release or a rebuilt manifest is a new key - a stale
cache is never read. Any cache failure (read-only disk, missing pyarrow) falls
back to the CSV path silently: the cache can make GlassMatch faster, never
different.

Location: GLASSMATCH_CACHE_DIR, else %LOCALAPPDATA%\\glassmatch\\cache on
Windows, else $XDG_CACHE_HOME/glassmatch or ~/.cache/glassmatch. Set
GLASSMATCH_CACHE=0 to disable.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pandas as pd


def enabled() -> bool:
    return os.environ.get("GLASSMATCH_CACHE", "1") != "0"


def root() -> Path:
    env = os.environ.get("GLASSMATCH_CACHE_DIR")
    if env:
        return Path(env)
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "glassmatch" / "cache"
    base = os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache")
    return Path(base) / "glassmatch"


def key(data_dir) -> str:
    """Hash of package version, data version and every CSV's size + mtime."""
    from glassmatch import __version__
    from glassmatch.manifest import read_manifest
    d = Path(data_dir)
    parts = [__version__, str((read_manifest(d) or {}).get("data_version"))]
    for p in sorted(d.glob("*.csv")):
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def directory(data_dir) -> Path | None:
    """This data's cache directory (created), or None when caching is off or
    the location is not writable."""
    if not enabled():
        return None
    try:
        p = root() / key(data_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p
    except OSError:
        return None


def frame(cache_dir: Path | None, name: str, build) -> pd.DataFrame:
    """A DataFrame from the cache, or build() it and store it."""
    if cache_dir is not None:
        path = cache_dir / f"{name}.parquet"
        if path.exists():
            try:
                return pd.read_parquet(path)
            except Exception:  # noqa: BLE001 - a bad cache file is just rebuilt
                pass
    df = build()
    if cache_dir is not None:
        try:
            df.to_parquet(cache_dir / f"{name}.parquet", index=False)
        except Exception:  # noqa: BLE001 - mixed-type column, read-only disk...
            try:
                (cache_dir / f"{name}.parquet").unlink(missing_ok=True)
            except OSError:
                pass
    return df


def obj(cache_dir: Path | None, name: str, build):
    """A JSON-serialisable object from the cache, or build() and store it."""
    if cache_dir is not None:
        path = cache_dir / f"{name}.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
    value = build()
    if cache_dir is not None:
        try:
            (cache_dir / f"{name}.json").write_text(
                json.dumps(value, default=_plain), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass
    return json.loads(json.dumps(value, default=_plain))


def _plain(v):
    """numpy scalars and other odd values -> JSON-able."""
    try:
        return v.item()
    except AttributeError:
        return str(v)
