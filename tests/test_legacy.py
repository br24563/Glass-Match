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
    # Parsed as CSV, not split on commas: catalog descriptions contain quoted
    # commas. The legacy layout is the first six columns.
    import pandas as pd
    g = pd.read_csv(src / "glasses.csv", encoding="utf-8", dtype=str)
    g.iloc[:, :6].to_csv(tmp_path / "glasses.csv", index=False,
                         encoding="utf-8")
    db = GlassDatabase.load(tmp_path)
    s = db.summary_frame()
    assert set(s["material_class"]) == {"oxide_glass"}
    assert set(s["status"]) == {"standard"}
