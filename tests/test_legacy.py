"""Backward-compat probe: legacy glasses.csv without new columns must load."""
from glassmatch.database import GlassDatabase


def test_legacy_glasses_without_new_columns(tmp_path):
    import shutil
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "data" / "normalized"
    for n in ("manufacturers.csv", "properties.csv", "sources.csv", "sellmeier.csv"):
        shutil.copy(src / n, tmp_path / n)
    lines = (src / "glasses.csv").read_text().splitlines()
    legacy = ["\n".join([",".join(l.split(",")[:6]) for l in lines])]
    (tmp_path / "glasses.csv").write_text(legacy[0])
    db = GlassDatabase.load(tmp_path)
    s = db.summary_frame()
    assert set(s["material_class"]) == {"oxide_glass"}
    assert set(s["status"]) == {"standard"}
