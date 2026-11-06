"""Database layer: loads the normalized CSV knowledge base."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd

def _default_data_dir() -> Path:
    """Where the shipped database lives.

    GLASSMATCH_DATA_DIR wins (a private or newer copy); then the repository
    checkout's data/normalized; then the copy an installed wheel carries as
    glassmatch/data (see pyproject.toml)."""
    import os
    env = os.environ.get("GLASSMATCH_DATA_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "data" / "normalized", here / "data"):
        if (cand / "glasses.csv").exists():
            return cand
    return here.parent / "data" / "normalized"


DEFAULT_DATA_DIR = _default_data_dir()

# The label a spectral_nk sample carries once both halves of a page's n and k
# tables have been merged onto one wavelength.  This string is already the
# dominant data_type in spectral_nk.csv ("literature (tabulated n,k)"), so
# merged rows join the existing vocabulary instead of inventing a new one.
NK_BOTH_LABELS = "literature (tabulated n,k)"

PROPERTY_LABELS = {
    "refractive_index_nd": "Refractive index (n_d)",
    "abbe_number_vd": "Abbe number (V_d)",
    "density": "Density",
    "cte": "CTE",
    "cte_20_300": "CTE (20/+300 C)",
    "tg": "Glass transition T_g",
    "thermal_conductivity": "Thermal conductivity",
    "youngs_modulus": "Young's modulus",
    "glass_code": "Glass code",
    "dPgF": "Anomalous partial dispersion dPg,F",
    "cte_100_300": "CTE (+100/+300 C)",
    "dn_dt_abs_d_20_40": "dn/dT absolute (d line, +20/+40 C)",
    "dn_dt_rel_d_20_40": "dn/dT relative to air (d line, +20/+40 C)",
    "td_D0": "dn/dT model D0", "td_D1": "dn/dT model D1",
    "td_D2": "dn/dT model D2", "td_E0": "dn/dT model E0",
    "td_E1": "dn/dT model E1", "td_lambda_tk": "dn/dT model lambda_tk",
    "td_T0": "dn/dT model reference temperature",
    "yield_point": "Yield point At",
    "specific_heat": "Specific heat",
    "shear_modulus": "Shear modulus",
    "poisson_ratio": "Poisson's ratio",
    "stress_optic_coefficient": "Stress-optic coefficient",
    "knoop_hardness": "Knoop hardness",
    "abrasion": "Abrasion",
    "relative_cost": "Relative cost",
    "climate_resistance": "Climate resistance (class)",
    "stain_resistance": "Stain resistance (class)",
    "acid_resistance": "Acid resistance (class)",
    "alkali_resistance": "Alkali resistance (class)",
    "phosphate_resistance": "Phosphate resistance (class)",
    "acid_resistance_surface": "Acid resistance, surface method (class)",
    "acid_resistance_powder": "Acid resistance, powder method (class)",
    "water_resistance_powder": "Water resistance, powder method (class)",
    "weathering_resistance_surface_max":
        "Weathering resistance, surface method, max (class)",
    "weathering_resistance_surface_min":
        "Weathering resistance, surface method, min (class)",
    "uv_edge_80_nm": "Colour code: lambda at 80 % T, 10 mm (catalog)",
    "uv_edge_70_nm": "Colour code: lambda at 70 % T, 10 mm (catalog)",
    "uv_edge_5_nm": "Colour code: lambda at 5 % T, 10 mm (catalog)",
    "uv_edge_internal_80_nm": "Internal colour code: lambda at 80 %, 10 mm",
    "uv_edge_internal_5_nm": "Internal colour code: lambda at 5 %, 10 mm",
    "strain_point": "Strain point (T14.5)",
    "annealing_point": "Annealing point (T13)",
    "softening_point": "Softening point (T7.6)",
    "grindability_class_iso": "Grindability class HG (ISO 12844)",
    "flexural_strength": "Flexural strength",
    "dn_dt_abs_e_20_40": "dn/dT absolute (e line, +20/+40 C)",
    "dn_dt_abs_g_20_40": "dn/dT absolute (g line, +20/+40 C)",
    "dn_dt_abs_1060_20_40": "dn/dT absolute (1060 nm, +20/+40 C)",
    "dn_dt_rel_1550_20_40": "dn/dT relative (1550 nm, +20/+40 C)",
}

# summary_frame column -> stored property. Every one is sortable in the
# Database explorer and selectable as an extra column / range filter in
# matching and `glassmatch search`.
SUMMARY_PROPERTIES = {
    "dpgf": "dPgF", "cte_20_300": "cte_20_300",
    "wl_min": "wl_min_um", "wl_max": "wl_max_um",
    "knoop": "knoop_hardness", "poisson": "poisson_ratio",
    "shear": "shear_modulus", "stress_optic": "stress_optic_coefficient",
    "specific_heat": "specific_heat", "flexural_strength": "flexural_strength",
    "strain_point": "strain_point", "annealing_point": "annealing_point",
    "yield_point": "yield_point", "softening_point": "softening_point",
    "uv_edge_80": "uv_edge_80_nm", "uv_edge_70": "uv_edge_70_nm",
    "uv_edge_5": "uv_edge_5_nm", "uv_edge_int80": "uv_edge_internal_80_nm",
    "uv_edge_int5": "uv_edge_internal_5_nm",
    "dn_dt_rel_1550": "dn_dt_rel_1550_20_40",
    "abrasion": "abrasion", "grindability_hg": "grindability_class_iso",
    "climate_resistance": "climate_resistance",
    "acid_resistance": "acid_resistance",
    "stain_resistance": "stain_resistance",
    "alkali_resistance": "alkali_resistance",
    "phosphate_resistance": "phosphate_resistance",
}
# Per-maker scales: filterable within one maker, never ranked across makers.
MAKER_SCALE_COLUMNS = {"abrasion", "grindability_hg", "climate_resistance",
                       "acid_resistance", "stain_resistance",
                       "alkali_resistance", "phosphate_resistance"}

PROPERTY_UNITS = {
    "refractive_index_nd": "",
    "abbe_number_vd": "",
    "density": "g/cm^3",
    "cte": "1e-6/K",
    "cte_20_300": "1e-6/K",
    "tg": "degC",
    "thermal_conductivity": "W/(m K)",
    "youngs_modulus": "GPa",
    "glass_code": "",
    "dn_dt_abs_d_20_40": "1e-6/K",
    "dn_dt_rel_d_20_40": "1e-6/K",
    "cte_100_300": "1e-6/K",
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
    spectral_nk: pd.DataFrame = field(default_factory=pd.DataFrame)
    equivalents: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Published nonlinear-index (n2) measurements of crystals, one row each.
    nonlinear_n2: pd.DataFrame = field(default_factory=pd.DataFrame)
    # Manufacturers' measured dn/dT: one row per glass, wavelength,
    # temperature interval and basis (relative / absolute), in 1e-6/K.
    dn_dt_measured: pd.DataFrame = field(default_factory=pd.DataFrame)

    @classmethod
    def load(cls, data_dir: Path | str = DEFAULT_DATA_DIR,
             use_cache: bool = True) -> "GlassDatabase":
        """Read the database. With use_cache, tables come from the local
        Parquet cache when it matches the CSVs exactly (glassmatch.cache);
        the CSVs are always the source of truth."""
        from glassmatch import cache as _cache
        data_dir = Path(data_dir)
        cdir = _cache.directory(data_dir) if use_cache else None

        def _read(name: str, required: bool = True) -> pd.DataFrame:
            path = data_dir / name
            if not path.exists():
                if required:
                    raise FileNotFoundError(f"Missing database file: {path}")
                return pd.DataFrame()
            # Encoding is explicit: manufacturer comments preserved in the
            # glass description are UTF-8, and a Windows locale default
            # (cp1252) would fail to decode them.
            return _cache.frame(cdir, "table_" + path.stem,
                                lambda: pd.read_csv(path, encoding="utf-8"))

        db = cls(
            data_dir=data_dir,
            manufacturers=_read("manufacturers.csv"),
            glasses=_read("glasses.csv"),
            properties=_read("properties.csv"),
            sources=_read("sources.csv"),
            sellmeier=_read("sellmeier.csv", required=False),
            transmission=_read("transmission.csv", required=False),
            spectral_nk=_read("spectral_nk.csv", required=False),
            equivalents=_read("equivalents.csv", required=False),
            nonlinear_n2=_read("nonlinear_n2.csv", required=False),
            dn_dt_measured=_read("dn_dt_measured.csv", required=False),
        )
        # Only a database read from disk may use the cache: one built in
        # memory (tests, imports) must never be answered from it.
        db.__dict__["_cache_dir"] = cdir
        for _col in ("material_class", "status"):
            if _col not in db.glasses.columns:
                db.glasses[_col] = "oxide_glass" if _col == "material_class" else "standard"
            else:
                default = "oxide_glass" if _col == "material_class" else "standard"
                db.glasses[_col] = db.glasses[_col].fillna(default).replace("", default)
        if not db.glasses.empty:
            db.glasses["glass_id"] = db.glasses["glass_id"].astype(str)
        for frame in (db.properties, db.sellmeier, db.spectral_nk):
            if not frame.empty and "glass_id" in frame.columns:
                frame["glass_id"] = frame["glass_id"].astype(str)
        return db

    def glass_ids(self) -> list:
        if self.glasses.empty:
            return []
        return self.glasses["glass_id"].astype(str).tolist()

    def _row_lookup(self, table: str, key: str) -> dict:
        """key value -> first row (a Series) of one table, built once.

        A boolean-mask lookup per call cost ~6 ms on the Arrow-backed string
        columns, and summary_frame makes one per glass: 18 s of a cold start.
        """
        cache = self.__dict__.setdefault("_row_lookups", {})
        if table not in cache or cache[table][0] is not getattr(self, table):
            frame = getattr(self, table)
            idx = {}
            if not frame.empty and key in frame.columns:
                for i, v in enumerate(frame[key].astype(str)):
                    idx.setdefault(v, i)
            cache[table] = (frame, idx)
        frame, idx = cache[table]
        return frame, idx

    def _get_row(self, table: str, key: str, value):
        frame, idx = self._row_lookup(table, key)
        i = idx.get(str(value))
        return frame.iloc[i] if i is not None else None

    def get_glass_row(self, glass_id: str):
        return self._get_row("glasses", "glass_id", glass_id)

    def get_manufacturer_row(self, manufacturer_id: str):
        return self._get_row("manufacturers", "manufacturer_id", manufacturer_id)

    def get_source_row(self, source_id: str):
        if self.sources.empty:
            return None
        return self._get_row("sources", "source_id", source_id)

    def properties_for(self, glass_id: str) -> pd.DataFrame:
        if self.properties.empty:
            return self.properties
        return self.properties[self.properties["glass_id"] == glass_id].copy()

    def property_value(self, glass_id: str, prop: str):
        v = self._property_index().get((str(glass_id), str(prop)))
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    def _property_columns(self) -> dict:
        """property -> {glass_id: float}, from the same priority index as
        property_value, built once. summary_frame reads ~40 properties for
        every glass; a property_value call each made it take ~10 s."""
        cols = self.__dict__.get("_prop_cols")
        if cols is None:
            cols = {}
            for (gid, prop), v in self._property_index().items():
                try:
                    cols.setdefault(prop, {})[gid] = float(v)
                except (TypeError, ValueError):
                    continue
            self.__dict__["_prop_cols"] = cols
        return cols

    def _property_index(self) -> dict:
        """(glass_id, property) -> value, preserving property_value's source
        priority (manufacturer > user_imported > calculated > interpolated >
        other; first row wins ties). Built once — O(rows) instead of
        O(glasses x rows) DataFrame scans."""
        idx = getattr(self, "_prop_idx", None)
        if idx is None:
            order = {"manufacturer": 0, "user_imported": 1,
                     "calculated": 2, "interpolated": 3}
            best = {}
            f = self.properties
            if not f.empty and {"glass_id", "property", "value"}.issubset(f.columns):
                dt = f["data_type"] if "data_type" in f.columns else pd.Series([""] * len(f))
                for i, (gid, prp, val, d) in enumerate(
                        zip(f["glass_id"], f["property"], f["value"], dt)):
                    r = order.get(str(d), 4)
                    key = (str(gid), str(prp))
                    cur = best.get(key)
                    if cur is None or r < cur[0]:
                        best[key] = (r, i, val)
            idx = {k: v[2] for k, v in best.items()}
            self._prop_idx = idx
        return idx

    def _transmission_ids(self) -> set:
        ids = getattr(self, "_t_ids", None)
        if ids is None:
            t = self.transmission
            ids = (set(t["glass_id"].astype(str))
                   if not t.empty and "glass_id" in t.columns else set())
            self._t_ids = ids
        return ids

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
        lst = self._sellmeier_rows().get(str(glass_id))
        if not lst:
            return None
        if sellmeier_only:
            from glassmatch.importers.agf import is_sellmeier1_formula
            for r in lst:
                if is_sellmeier1_formula(r.get("formula")):
                    return r
            return None
        return lst[0]

    def _sellmeier_rows(self) -> dict:
        """glass_id -> [row dicts in file order]; built once. Preserves
        sellmeier_for's first-row-wins semantics (incl. the sellmeier_only
        filter taking the first verified row)."""
        rows = getattr(self, "_sm_rows", None)
        if rows is None:
            rows = {}
            f = self.sellmeier
            if not f.empty and "glass_id" in f.columns:
                for _, r in f.iterrows():
                    rows.setdefault(str(r["glass_id"]), []).append(r.to_dict())
            self._sm_rows = rows
        return rows

    def dispersion_status(self, glass_id: str) -> str:
        """'sellmeier1' | 'archived-non-sellmeier' | 'none' — drives UI gating.

        'sellmeier1' is the historical name for "has a verified dispersion
        fit"; the fit may be any Zemax formula (Schott, Extended 3 ...)."""
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

    def _spectral_nk_index(self) -> dict:
        """glass_id -> {wavelength_um: (n, k, data_type)}, built once.

        spectral_nk.csv is the largest table in the database (~135k rows), so
        the per-glass slice is memoized rather than rescanned per plot.

        A reference page may publish n and k as two separate tables, and the
        importer stores them as separate rows sharing wavelengths (RII-SI-GREEN-1995
        and RII-AL2O3-QUERRY do).  Rows at one wavelength are therefore merged
        rather than keyed: keying a dict straight off the wavelength let the
        later row replace the earlier one, which dropped 76 of that silicon
        page's 121 tabulated n samples and made its table look like it started
        at 1.01 um, so n_at reported "unavailable" for wavelengths the cited
        reference plainly tabulates.  The label of a merged row says so.
        """
        idx = getattr(self, "_nk_idx", None)
        if idx is None:
            idx = {}
            f = self.spectral_nk
            if not f.empty and "glass_id" in f.columns:
                cols = set(f.columns)
                has_n, has_k = "n" in cols, "k" in cols
                n_source = f["n"] if has_n else None
                k_source = f["k"] if has_k else None
                dt_source = (f["data_type"] if "data_type" in cols
                             else pd.Series(["literature"] * len(f), index=f.index))
                for gid, grp in f.groupby("glass_id", sort=False):
                    merged: dict = {}
                    for w, n, k, dt in zip(grp["wavelength_um"],
                                          n_source.loc[grp.index] if has_n else [None] * len(grp),
                                          k_source.loc[grp.index] if has_k else [None] * len(grp),
                                          dt_source.loc[grp.index]):
                        if not has_n or pd.isna(n):
                            n = None
                        if not has_k or pd.isna(k):
                            k = None
                        entry = merged.setdefault(float(w), {"n": None, "k": None,
                                                             "labels": set()})
                        if n is not None:
                            if entry["n"] is None:      # first value wins; a
                                entry["n"] = float(n)   # disagreement is data
                                entry["labels"].add(str(dt))  # quality, not ours
                        if k is not None:               # to resolve silently.
                            if entry["k"] is None:
                                entry["k"] = float(k)
                                entry["labels"].add(str(dt))
                    idx[str(gid)] = {
                        w: (v["n"], v["k"],
                            NK_BOTH_LABELS if (v["n"] is not None and v["k"] is not None
                                               and len(v["labels"]) > 1)
                            else (next(iter(v["labels"])) if v["labels"] else "literature"))
                        for w, v in merged.items()}
            self._nk_idx = idx
        return idx

    def spectral_nk_for(self, glass_id: str) -> pd.DataFrame | None:
        """Tabulated n/k for a crystal, or None when the page had no table."""
        pts = self._spectral_nk_index().get(str(glass_id))
        if not pts:
            return None
        rows = [{"wavelength_um": w, "n": n, "k": k, "data_type": dt}
                for w, (n, k, dt) in sorted(pts.items())]
        return pd.DataFrame(rows)

    def n_at(self, glass_id: str, wavelength_nm: float):
        """n at a reference wavelength, plus how it was obtained.

        Returns (value, data_type) or (None, None).  This is the property that
        makes glasses and crystals comparable: it resolves, in order,

          1. a stored `n_at_reference` row (crystals from the literature
             pages; also any imported page that supplied one),
          2. interpolation over tabulated `spectral_nk` samples,
          3. evaluation of the glass's own verified Sellmeier coefficients -
             which is how a glass answers for an arbitrary wavelength such as
             10 um, where it has no tabulated n_d and no catalogue entry.

        Every branch reports its own basis, and nothing is extrapolated
        outside a source's stated range.
        """
        gid = str(glass_id)
        tol = wavelength_nm * 1e-4
        for wl_nm, value, dtype in self._n_reference_index().get(gid, ()):
            if abs(wl_nm - wavelength_nm) < tol:
                return value, dtype
        df = self.spectral_nk_for(gid)
        if df is not None and len(df):
            pts = df.dropna(subset=["n"])
            if len(pts) >= 2:
                w_um = wavelength_nm / 1000.0
                lo, hi = (float(pts["wavelength_um"].min()),
                          float(pts["wavelength_um"].max()))
                if lo <= w_um <= hi:
                    from glassmatch.importers.refractiveindex_yaml import _interp
                    # _interp reads (wavelength_um, n) pairs; the third zip
                    # argument of an earlier draft made zip() iterate None and
                    # raised before _interp was reached, so this branch - the
                    # only way a crystal answers an off-grid wavelength - was
                    # dead for 123 of the 124 materials that can use it.
                    val, _rng = _interp(
                        w_um, list(zip(pts["wavelength_um"], pts["n"])))
                    if val is not None and val == val:
                        return float(val), "interpolated"
        coef = self.sellmeier_for(gid, sellmeier_only=True)
        if coef is not None:
            lo, hi = self.dispersion_range(gid, coef)
            w_um = wavelength_nm / 1000.0
            if lo is None or hi is None or (lo <= w_um <= hi):
                from glassmatch.spectra import n_from_row
                val = n_from_row(coef, w_um)
                if val == val and val > 0:
                    return float(val), "calculated"
        return None, None

    def _n_reference_index(self) -> dict:
        """glass_id -> [(wavelength_nm, n, data_type)] for stored
        n_at_reference rows, in file order (first match wins), built once.
        Filtering the whole properties table per call made n_at for every
        material take ~50 s."""
        idx = self.__dict__.get("_nref_idx")
        if idx is None:
            idx = {}
            f = self.properties
            if not f.empty and "property" in f.columns:
                hit = f[f["property"] == "n_at_reference"]
                wl = pd.to_numeric(hit["reference_wavelength_nm"], errors="coerce")
                val = pd.to_numeric(hit["value"], errors="coerce")
                dts = (hit["data_type"].astype(str) if "data_type" in hit.columns
                       else [""] * len(hit))
                for gid, w, v, dt in zip(hit["glass_id"].astype(str), wl, val, dts):
                    if w == w and v == v:
                        idx.setdefault(gid, []).append((float(w), float(v), dt))
            self.__dict__["_nref_idx"] = idx
        return idx

    def dispersion_range(self, glass_id: str, coef: dict):
        """Validity range (um) for a dispersion curve, or (None, None).

        A fit evaluated outside the range its source states is an
        extrapolation, not a measurement, and GlassMatch does not report one:
        the Malitson CaF2 fit is declared valid to 9.7 um, so a request at
        10 um returns "unavailable" rather than a smooth invented number.
        refractiveindex rows carry their own "lo-hi"; for the manufacturer
        .agf rows the catalog's own LD wavelength limits are used instead.
        """
        rng = str(coef.get("wavelength_um", "") or "").strip()
        if "-" in rng:
            parts = rng.split("-", 1)
            try:
                return float(parts[0]), float(parts[1])
            except ValueError:
                pass
        # Through the cached property index: the Fresnel fallback asks this
        # for every wavelength of every glass, and a DataFrame scan per call
        # made a full matching run take minutes once every catalog had fits.
        lo = self.property_value(glass_id, "wl_min_um")
        hi = self.property_value(glass_id, "wl_max_um")
        if lo is not None and hi is not None and lo == lo and hi == hi \
                and lo > 0 and hi > 0:
            return lo, hi
        return None, None

    def cache_dir(self):
        """This database's cache directory, or None (in-memory database)."""
        return self.__dict__.get("_cache_dir")

    def summary_frame(self) -> pd.DataFrame:
        """One row per glass with every sortable stored property (cached)."""
        from glassmatch import cache as _cache
        return _cache.frame(self.cache_dir(), "summary", self._build_summary)

    def data_tiers(self) -> dict:
        """glass_id -> where its core data comes from:

        * "manufacturer" - a maker's own current catalog or workbook;
        * "literature"   - a published measurement (refractiveindex.info);
        * "unverified_mirror" - only a third-party mirror of unknown date
          (license 'mirror-vintage-unknown'): the glass may no longer be
          made, or made to these numbers, so searches hide it by default.

        Judged by the source of the glass's catalog n_d, else of its
        dispersion fit. A dated mirror of a maker's current file (HOYA's
        2026-04-01 workbook) is not "unverified".
        """
        cached = self.__dict__.get("_data_tiers")
        if cached is not None:
            return cached
        lic = {}
        if not self.sources.empty:
            lic = dict(zip(self.sources["source_id"].astype(str),
                           self.sources["license"].fillna("").astype(str)))
        src = {}
        if not self.sellmeier.empty and "source_id" in self.sellmeier.columns:
            for g, s in zip(self.sellmeier["glass_id"].astype(str),
                            self.sellmeier["source_id"].astype(str)):
                src.setdefault(g, s)
        if not self.properties.empty:
            nd = self.properties[self.properties["property"] == "refractive_index_nd"]
            for g, s in zip(nd["glass_id"].astype(str), nd["source_id"].astype(str)):
                src[g] = s                      # catalog n_d wins
        out = {}
        for g, mid in zip(self.glasses["glass_id"].astype(str),
                          self.glasses["manufacturer_id"].astype(str)):
            licence = lic.get(src.get(g, ""), "")
            out[g] = ("unverified_mirror" if licence.startswith("mirror-vintage-unknown")
                      else "literature" if mid == "RII" else "manufacturer")
        self.__dict__["_data_tiers"] = out
        return out

    def _build_summary(self) -> pd.DataFrame:
        """One row per glass with every sortable stored property.

        Built from plain dicts: iterrows() and a DataFrame row lookup per
        glass (manufacturer name) cost ~8 s on the Arrow-backed columns."""
        import pandas as pd  # local import keeps module light
        if self.glasses.empty:
            return pd.DataFrame()
        cols = self._property_columns()

        def pv(gid, prop):
            return cols.get(prop, {}).get(gid)
        names = {}
        if not self.manufacturers.empty:
            for mid, name in zip(self.manufacturers["manufacturer_id"].astype(str),
                                 self.manufacturers["name"].astype(str)):
                names.setdefault(mid, name)
        t_ids = self._transmission_ids()
        tiers = self.data_tiers()

        def text(g, key, default=""):
            v = g.get(key)
            return default if v is None or v != v or v == "" else str(v)
        rows = []
        for g in self.glasses.to_dict(orient="records"):
            gid = str(g["glass_id"])
            mid = text(g, "manufacturer_id")
            status = self.dispersion_status(gid)
            rows.append({
                "glass_id": gid,
                "glass": text(g, "glass_name", gid),
                "manufacturer": names.get(mid, mid),
                "manufacturer_id": mid,
                "family": text(g, "glass_family"),
                "material_class": text(g, "material_class", "oxide_glass"),
                "status": text(g, "status", "standard"),
                "nd": pv(gid, "refractive_index_nd"),
                "vd": pv(gid, "abbe_number_vd"),
                "density": pv(gid, "density"),
                "cte": pv(gid, "cte"),
                "tg": pv(gid, "tg"),
                "k_thermal": pv(gid, "thermal_conductivity"),
                "young": pv(gid, "youngs_modulus"),
                # Manufacturer figures win over values derived from TD
                # coefficients (property_value's source priority).
                "dn_dt": pv(gid, "dn_dt_abs_d_20_40"),
                "relative_cost": pv(gid, "relative_cost"),
                **{col: pv(gid, prop)
                   for col, prop in SUMMARY_PROPERTIES.items()},
                "production_frequency": text(g, "production_frequency"),
                "has_sellmeier": status == "sellmeier1",
                "dispersion": status,
                "data_tier": tiers.get(gid, "manufacturer"),
                "has_transmission": gid in t_ids,
                "description": text(g, "description"),
            })
        return pd.DataFrame(rows)


def load_default_database(data_dir: Path | str = DEFAULT_DATA_DIR) -> GlassDatabase:
    return GlassDatabase.load(data_dir)

