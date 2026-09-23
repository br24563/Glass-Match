"""Source/provenance helpers + importer for user CSVs."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

USER_COLUMNS = ["name", "manufacturer", "nd", "vd", "density",
                "cte", "thermal_conductivity", "source"]


def describe_source(db, source_id: str) -> dict:
    row = db.get_source_row(str(source_id))
    if row is None:
        return {"source_id": source_id}
    return row.to_dict()


def importers_list() -> list:
    return ["generic_csv", "spectral_csv", "zemax_agf"]


def import_user_glasses(csv_path: Path | str) -> tuple[pd.DataFrame, pd.DataFrame, list]:
    """Validate + normalize a user CSV into (glasses, properties, issues)."""
    from glassmatch.validation import validate_property_frame
    src = pd.read_csv(csv_path)
    issues, grows, prows = [], [], []
    for i, r in src.iterrows():
        name = str(r.get("name", "")).strip()
        mfr = str(r.get("manufacturer", "")).strip() or "USER"
        if not name:
            issues.append({"row": i, "issue": "missing name"})
            continue
        gid = f"USER-{mfr}-{name}".upper().replace(" ", "_")
        grows.append({"glass_id": gid, "manufacturer_id": mfr, "glass_name": name,
                      "manufacturer_code": name, "glass_family": "User imported",
                      "description": "User-imported record."})
        for col, prop in [("nd", "refractive_index_nd"), ("vd", "abbe_number_vd"),
                          ("density", "density"), ("cte", "cte"),
                          ("thermal_conductivity", "thermal_conductivity")]:
            if col in src.columns and pd.notna(r.get(col)):
                try:
                    prows.append({"glass_id": gid, "property": prop,
                                  "value": float(r[col]), "unit": "",
                                  "reference_wavelength_nm": 587.6 if prop == "refractive_index_nd" else "",
                                  "data_type": "user_imported", "source_id": "USER-IMPORT",
                                  "notes": str(r.get("source", ""))})
                except (TypeError, ValueError):
                    issues.append({"row": i, "issue": f"bad {col}", "value": r.get(col)})
    g = pd.DataFrame(grows)
    p = pd.DataFrame(prows)
    issues += validate_property_frame(p) if not p.empty else []
    return g, p, issues
