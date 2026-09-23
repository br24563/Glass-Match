"""Generic CSV -> normalized GlassMatch frames (no app logic changes needed)."""
from __future__ import annotations
from pathlib import Path
import pandas as pd


COLUMN_MAP = {
    "glass": "glass_name", "name": "glass_name", "glass_name": "glass_name",
    "manufacturer": "manufacturer_id", "mfr": "manufacturer_id",
    "nd": "refractive_index_nd", "n_d": "refractive_index_nd",
    "vd": "abbe_number_vd", "v_d": "abbe_number_vd",
    "density": "density", "rho": "density",
    "cte": "cte", "alpha": "cte",
    "tg": "tg", "thermal_conductivity": "thermal_conductivity",
    "youngs_modulus": "youngs_modulus",
}


def normalize_frame(raw: pd.DataFrame, manufacturer: str,
                    source_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    rename = {c: COLUMN_MAP.get(str(c).strip().lower(), c) for c in raw.columns}
    df = raw.rename(columns=rename)
    grows, prows = [], []
    for _, r in df.iterrows():
        name = str(r.get("glass_name", "")).strip()
        if not name:
            continue
        mfr = str(r.get("manufacturer_id", manufacturer)).strip() or manufacturer
        gid = f"{mfr}-{name}".upper().replace(" ", "_")
        grows.append({"glass_id": gid, "manufacturer_id": mfr, "glass_name": name,
                      "manufacturer_code": name, "glass_family": str(r.get("glass_family", "Imported")),
                      "description": "Imported via generic_csv importer."})
        for prop in ("refractive_index_nd", "abbe_number_vd", "density", "cte",
                     "tg", "thermal_conductivity", "youngs_modulus"):
            if prop in df.columns and pd.notna(r.get(prop)):
                try:
                    prows.append({"glass_id": gid, "property": prop, "value": float(r[prop]),
                                  "unit": "", "reference_wavelength_nm": 587.6 if prop == "refractive_index_nd" else "",
                                  "data_type": "user_imported", "source_id": source_id, "notes": ""})
                except (TypeError, ValueError):
                    continue
    return pd.DataFrame(grows), pd.DataFrame(prows)


def import_csv(path: Path | str, manufacturer: str = "USER",
               source_id: str = "USER-IMPORT") -> tuple[pd.DataFrame, pd.DataFrame]:
    return normalize_frame(pd.read_csv(path), manufacturer, source_id)
