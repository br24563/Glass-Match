"""Database layer: loads the normalized CSV knowledge base."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "normalized"

PROPERTY_LABELS = {
    "refractive_index_nd": "Refractive index (n_d)",
    "abbe_number_vd": "Abbe number (V_d)",
    "density": "Density",
    "cte": "CTE",
    "tg": "Glass transition T_g",
    "thermal_conductivity": "Thermal conductivity",
    "youngs_modulus": "Young's modulus",
    "glass_code": "Glass code",
}

PROPERTY_UNITS = {
    "refractive_index_nd": "",
    "abbe_number_vd": "",
    "density": "g/cm^3",
    "cte": "1e-6/K",
    "tg": "degC",
    "thermal_conductivity": "W/(m K)",
    "youngs_modulus": "GPa",
    "glass_code": "",
}


@dataclass
class GlassDatabase:
    data_dir: Path = field(default_factory=lambda: DEFAULT_DATA_DIR)
    manufacturers: pd.DataFrame = field(default_factory=pd.DataFrame)
    glasses: pd.DataFrame = field(default_factory=pd.DataFrame)
    properties: pd.DataFrame = field(default_factory=pd.DataFrame)
    sources: pd.DataFrame = field(default_factory=pd.DataFrame)
    sellmeier: pd.DataFrame = field(default_factory=pd.DataFrame)
    transmission: pd.DataFrame = field(default_factory=pd.DataFrame)
    equivalents: pd.DataFrame = field(default_factory=pd.DataFrame)
    @classmethod
    def load(cls, data_dir: Path | str = DEFAULT_DATA_DIR) -> "GlassDatabase":
        data_dir = Path(data_dir)

        def _read(name: str, required: bool = True) -> pd.DataFrame:
            path = data_dir / name
            if not path.exists():
                if required:
                    raise FileNotFoundError(f"Missing database file: {path}")
                return pd.DataFrame()
            return pd.read_csv(path)

        db = cls(
            data_dir=data_dir,
            manufacturers=_read("manufacturers.csv"),
            glasses=_read("glasses.csv"),
            properties=_read("properties.csv"),
            sources=_read("sources.csv"),
            sellmeier=_read("sellmeier.csv", required=False),
            transmission=_read("transmission.csv", required=False),
            equivalents=_read("equivalents.csv", required=False),
        )
        for _col in ("material_class", "status"):
            if _col not in db.glasses.columns:
                db.glasses[_col] = "oxide_glass" if _col == "material_class" else "standard"
            else:
                default = "oxide_glass" if _col == "material_class" else "standard"
                db.glasses[_col] = db.glasses[_col].fillna(default).replace("", default)
        if not db.glasses.empty:
            db.glasses["glass_id"] = db.glasses["glass_id"].astype(str)
        for frame in (db.properties, db.sellmeier):
            if not frame.empty and "glass_id" in frame.columns:
                frame["glass_id"] = frame["glass_id"].astype(str)
        return db

    def glass_ids(self) -> list:
        if self.glasses.empty:
            return []
        return self.glasses["glass_id"].astype(str).tolist()

    def get_glass_row(self, glass_id: str):
        hit = self.glasses[self.glasses["glass_id"] == glass_id]
        return hit.iloc[0] if not hit.empty else None

    def get_manufacturer_row(self, manufacturer_id: str):
        hit = self.manufacturers[self.manufacturers["manufacturer_id"] == manufacturer_id]
        return hit.iloc[0] if not hit.empty else None

    def get_source_row(self, source_id: str):
        if self.sources.empty:
            return None
        hit = self.sources[self.sources["source_id"] == source_id]
        return hit.iloc[0] if not hit.empty else None

    def properties_for(self, glass_id: str) -> pd.DataFrame:
        if self.properties.empty:
            return self.properties
        return self.properties[self.properties["glass_id"] == glass_id].copy()

    def property_value(self, glass_id: str, prop: str):
        frame = self.properties_for(glass_id)
        frame = frame[frame["property"] == prop]
        if frame.empty:
            return None
        order = {"manufacturer": 0, "user_imported": 1, "calculated": 2, "interpolated": 3}
        frame = frame.copy()
        frame["_o"] = frame["data_type"].map(lambda v: order.get(str(v), 4))
        frame = frame.sort_values("_o")
        try:
            return float(frame.iloc[0]["value"])
        except (TypeError, ValueError):
            return None

    def property_provenance(self, glass_id: str, prop: str) -> list:
        frame = self.properties_for(glass_id)
        frame = frame[frame["property"] == prop]
        rows = []
        for _, r in frame.iterrows():
            src = self.get_source_row(str(r.get("source_id", "")))
            rows.append({
                "value": r.get("value"), "unit": r.get("unit", ""),
                "reference_wavelength_nm": r.get("reference_wavelength_nm", ""),
                "data_type": r.get("data_type", ""),
                "source_id": r.get("source_id", ""),
                "source_name": src["source_name"] if src is not None else "",
                "source_url": src["source_url"] if src is not None else "",
                "license": src["license"] if src is not None else "",
                "notes": r.get("notes", ""),
            })
        return rows

    def sellmeier_for(self, glass_id: str, sellmeier_only: bool = False):
        if self.sellmeier.empty:
            return None
        hit = self.sellmeier[self.sellmeier["glass_id"] == glass_id]
        if hit.empty:
            return None
        if sellmeier_only:
            from glassmatch.importers.agf import is_sellmeier1_formula
            hit = hit[hit["formula"].map(is_sellmeier1_formula)]
            if hit.empty:
                return None
        return hit.iloc[0].to_dict()

    def dispersion_status(self, glass_id: str) -> str:
        """'sellmeier1' | 'archived-non-sellmeier' | 'none' — drives UI gating."""
        row = self.sellmeier_for(glass_id)
        if row is None:
            return "none"
        from glassmatch.importers.agf import is_sellmeier1_formula
        return "sellmeier1" if is_sellmeier1_formula(row.get("formula")) else "archived-non-sellmeier"

    def equivalents_for(self, glass_id: str) -> pd.DataFrame:
        if self.equivalents.empty:
            return self.equivalents
        return self.equivalents[(self.equivalents["glass_id_a"] == glass_id) |
                                (self.equivalents["glass_id_b"] == glass_id)].copy()

    def summary_frame(self) -> pd.DataFrame:
        import pandas as pd  # local import keeps module light
        if self.glasses.empty:
            return pd.DataFrame()
        rows = []
        for _, g in self.glasses.iterrows():
            gid = str(g["glass_id"])
            mfr = self.get_manufacturer_row(str(g.get("manufacturer_id", "")))
            has_trans = (not self.transmission.empty
                         and "glass_id" in self.transmission.columns
                         and bool((self.transmission["glass_id"] == gid).any()))
            rows.append({
                "glass_id": gid,
                "glass": str(g.get("glass_name", gid)),
                "manufacturer": str(mfr["name"]) if mfr is not None else str(g.get("manufacturer_id", "")),
                "manufacturer_id": str(g.get("manufacturer_id", "")),
                "family": str(g.get("glass_family", "")),
                "material_class": str(g.get("material_class", "") or "oxide_glass"),
                "status": str(g.get("status", "") or "standard"),
                "nd": self.property_value(gid, "refractive_index_nd"),
                "vd": self.property_value(gid, "abbe_number_vd"),
                "density": self.property_value(gid, "density"),
                "cte": self.property_value(gid, "cte"),
                "tg": self.property_value(gid, "tg"),
                "k_thermal": self.property_value(gid, "thermal_conductivity"),
                "young": self.property_value(gid, "youngs_modulus"),
                "has_sellmeier": self.dispersion_status(gid) == "sellmeier1",
                "dispersion": self.dispersion_status(gid),
                "has_transmission": bool(has_trans),
                "description": str(g.get("description", "")),
            })
        return pd.DataFrame(rows)


def load_default_database(data_dir: Path | str = DEFAULT_DATA_DIR) -> GlassDatabase:
    return GlassDatabase.load(data_dir)

