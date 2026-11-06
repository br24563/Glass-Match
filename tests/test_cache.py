"""The local derived-data cache (glassmatch.cache) makes loads faster, never
different: every table read back from it equals the CSV load exactly."""
import pandas as pd
import pytest

from glassmatch import cache
from glassmatch.database import DEFAULT_DATA_DIR, GlassDatabase
from glassmatch.derived import optical_figures

TABLES = ("manufacturers", "glasses", "properties", "sources", "sellmeier",
          "transmission", "spectral_nk", "equivalents")


@pytest.fixture(scope="module")
def pair(tmp_path_factory):
    import os
    old = os.environ.get("GLASSMATCH_CACHE_DIR")
    os.environ["GLASSMATCH_CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))
    try:
        plain = GlassDatabase.load(DEFAULT_DATA_DIR, use_cache=False)
        GlassDatabase.load(DEFAULT_DATA_DIR).summary_frame()      # writes
        cached = GlassDatabase.load(DEFAULT_DATA_DIR)              # reads
        yield plain, cached
    finally:
        if old is None:
            os.environ.pop("GLASSMATCH_CACHE_DIR", None)
        else:
            os.environ["GLASSMATCH_CACHE_DIR"] = old


def test_tables_identical(pair):
    plain, cached = pair
    assert cached.cache_dir() is not None and plain.cache_dir() is None
    assert (cached.cache_dir() / "table_glasses.parquet").exists()
    for t in TABLES:
        pd.testing.assert_frame_equal(getattr(plain, t), getattr(cached, t),
                                      obj=t)


def test_derived_identical(pair):
    plain, cached = pair
    pd.testing.assert_frame_equal(plain.summary_frame(), cached.summary_frame())
    pd.testing.assert_frame_equal(optical_figures(plain), optical_figures(cached))


def test_disabled_and_in_memory(monkeypatch, tmp_path):
    monkeypatch.setenv("GLASSMATCH_CACHE", "0")
    assert cache.directory(DEFAULT_DATA_DIR) is None
    db = GlassDatabase.load(DEFAULT_DATA_DIR)
    assert db.cache_dir() is None
    calls = []
    out = cache.frame(None, "x", lambda: calls.append(1) or pd.DataFrame({"a": [1]}))
    assert calls == [1] and list(out["a"]) == [1]


def test_key_changes_with_data(tmp_path):
    (tmp_path / "glasses.csv").write_text("glass_id\nA\n", encoding="utf-8")
    k1 = cache.key(tmp_path)
    (tmp_path / "glasses.csv").write_text("glass_id\nA\nB\n", encoding="utf-8")
    assert cache.key(tmp_path) != k1


def test_bad_cache_file_is_rebuilt(tmp_path):
    (tmp_path / "x.parquet").write_bytes(b"not parquet")
    out = cache.frame(tmp_path, "x", lambda: pd.DataFrame({"a": [2]}))
    assert list(out["a"]) == [2]
    assert list(pd.read_parquet(tmp_path / "x.parquet")["a"]) == [2]


def test_key_changes_with_code(monkeypatch, tmp_path):
    """A calculation fix must not be answered from a cache the old code built."""
    (tmp_path / "glasses.csv").write_text("glass_id\nA\n", encoding="utf-8")
    k1 = cache.key(tmp_path)
    monkeypatch.setattr(cache, "_CODE_FP", "different-code")
    assert cache.key(tmp_path) != k1
