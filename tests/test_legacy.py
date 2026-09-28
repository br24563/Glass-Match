"""Backward-compat probe: legacy glasses.csv without new columns must load."""
from glassmatch.database import GlassDatabase


def test_legacy_glasses_without_new_columns(tmp_path):
    import shutil
    from pathlib import Path
    src = Path(__file__).resolve().parents[1] / "data" / "normalized"
    for n in ("manufacturers.csv", "properties.csv", "sources.csv", "sellmeier.csv"):
        shutil.copy(src / n, tmp_path / n)
    # Encoding is explicit: the committed CSVs are UTF-8 and the Windows
    # locale default (cp1252) cannot decode them.
    lines = (src / "glasses.csv").read_text(encoding="utf-8").splitlines()
    legacy = ["\n".join([",".join(l.split(",")[:6]) for l in lines])]
    (tmp_path / "glasses.csv").write_text(legacy[0], encoding="utf-8")
    db = GlassDatabase.load(tmp_path)
    s = db.summary_frame()
    assert set(s["material_class"]) == {"oxide_glass"}
    assert set(s["status"]) == {"standard"}
