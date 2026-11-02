"""Every sortable per-glass column, stored or derived, with its label.

One place builds the table the app's extra columns / range filters, the
Database explorer and `glassmatch search --columns/--where/--sort` all use, so
they cannot drift apart. Stored columns come from GlassDatabase.summary_frame;
derived ones from glassmatch.derived and are labelled "(calculated)".
"""
from __future__ import annotations

import pandas as pd

from glassmatch import derived as dv
from glassmatch.database import (MAKER_SCALE_COLUMNS, PROPERTY_LABELS,
                                 SUMMARY_PROPERTIES)

# summary_frame columns that are not properties.csv rows of the same name.
_BASE_LABELS = {
    "nd": ("n_d", ""), "vd": ("V_d", ""), "density": ("density", "g/cm³"),
    "cte": ("CTE −30/+70 °C", "1e-6/K"), "tg": ("T_g", "°C"),
    "k_thermal": ("thermal conductivity", "W/(m K)"),
    "young": ("Young's modulus", "GPa"),
    "dn_dt": ("dn/dT absolute, d line, +20/+40 °C", "1e-6/K"),
    "relative_cost": ("relative cost (maker's reference glass = 1)", ""),
    "production_frequency": ("melt / production frequency (maker's code)", ""),
}
_UNITS = {
    "dpgf": "", "cte_20_300": "1e-6/K", "wl_min": "um", "wl_max": "um",
    "knoop": "HK", "poisson": "", "shear": "GPa", "stress_optic": "1e-12/Pa",
    "specific_heat": "J/(g K)", "flexural_strength": "MPa",
    "strain_point": "°C", "annealing_point": "°C", "yield_point": "°C",
    "softening_point": "°C", "uv_edge_80": "nm", "uv_edge_70": "nm",
    "uv_edge_5": "nm", "uv_edge_int80": "nm", "uv_edge_int5": "nm",
    "dn_dt_rel_1550": "1e-6/K", "abrasion": "", "grindability_hg": "class",
    "climate_resistance": "class", "acid_resistance": "class",
    "stain_resistance": "class", "alkali_resistance": "class",
    "phosphate_resistance": "class",
}


def labels() -> dict:
    """column -> (label, unit) for every column columns() can return."""
    out = dict(_BASE_LABELS)
    for col, prop in SUMMARY_PROPERTIES.items():
        label = PROPERTY_LABELS.get(prop, prop.replace("_", " "))
        if col in MAKER_SCALE_COLUMNS:
            label += " - maker's own scale"
        out[col] = (label, _UNITS.get(col, ""))
    out.update(dv.LABELS)
    return out


def columns(db, summary: pd.DataFrame, t_groups: dict | None = None,
            thickness_mm: float = 10.0,
            wavelength_nm: float | None = None) -> pd.DataFrame:
    """glass_id-indexed table of every stored and derived column.

    t_groups (glass_id -> transmission rows) enables the transmission
    figures at `thickness_mm`; wavelength_nm enables n / dn/dlambda / group
    index / GVD at that wavelength. Both are optional because they cost a
    second or two each."""
    keep = [c for c in labels() if c in summary.columns]
    out = summary.set_index("glass_id")[keep].copy()
    parts = [dv.optical_figures(db), dv.thermo_mechanical(summary)]
    if t_groups is not None:
        parts.append(dv.transmission_figures(t_groups, thickness_mm))
    if wavelength_nm is not None:
        parts.append(dv.at_wavelength(db, wavelength_nm))
    for p in parts:
        if not p.empty:
            out = out.join(p, how="left")
    return out


def range_filter(table: pd.DataFrame, where: dict,
                 keep_missing: bool = True) -> pd.Series:
    """Boolean mask: rows whose every `col` lies in where[col] = (lo, hi).
    A row with no value is kept (flagged elsewhere) unless keep_missing is
    False - the same rule as "Require available data"."""
    mask = pd.Series(True, index=table.index)
    for col, (lo, hi) in where.items():
        v = pd.to_numeric(table[col], errors="coerce")
        ok = pd.Series(True, index=table.index)
        if lo is not None:
            ok &= v >= lo
        if hi is not None:
            ok &= v <= hi
        mask &= ok | (v.isna() if keep_missing else False)
    return mask
