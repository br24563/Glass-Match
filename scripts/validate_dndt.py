"""Check the SCHOTT dn/dT model (TD records) against the makers' measured
dn/dT tables, interval by interval.

    python scripts/validate_dndt.py [--worst N]

For every glass that has both, and every measured value whose wavelength and
temperature interval lie inside the model's stated validity (-100 ... +140 C,
365 ... 1014 nm), the model's mean dn/dT over the same interval (absolute, or
relative to air at normal pressure) is compared with the maker's number.
The makers print one decimal, so |difference| <= 0.05e-6/K is agreement to
the printed precision. Results are summarised in docs/VALIDATION.md.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.database import GlassDatabase  # noqa: E402
from glassmatch.spectra import delta_n_abs  # noqa: E402
from glassmatch.thermal import (P0, TD_T_RANGE, TD_WL_RANGE_UM,  # noqa: E402
                                air_index, td_record)


def compare(db) -> pd.DataFrame:
    m = db.dn_dt_measured
    rows = []
    for gid, grp in m.groupby("glass_id"):
        td = td_record(db, gid)
        if td is None:
            continue
        for wl, g2 in grp.groupby("wavelength_um"):
            if not (TD_WL_RANGE_UM[0] <= wl <= TD_WL_RANGE_UM[1]):
                continue
            n0, _ = db.n_at(gid, wl * 1000.0)
            if n0 is None:
                continue
            a0 = air_index(wl, td[6], P0)

            def n_t(t, absolute):
                n_abs = n0 * a0 + delta_n_abs(td, n0, wl, t)
                return n_abs if absolute else n_abs / air_index(wl, t, P0)
            for r in g2.itertuples():
                lo, hi = float(r.t_lo_c), float(r.t_hi_c)
                if lo < TD_T_RANGE[0] or hi > TD_T_RANGE[1]:
                    continue
                ab = r.basis == "absolute"
                model = (n_t(hi, ab) - n_t(lo, ab)) / (hi - lo) * 1e6
                rows.append({"glass_id": gid, "source_id": r.source_id,
                             "basis": r.basis, "wavelength_um": wl,
                             "t_lo_c": lo, "t_hi_c": hi,
                             "measured": r.dn_dt, "model": model,
                             "diff": r.dn_dt - model,
                             "reference_only": r.reference_only})
    return pd.DataFrame(rows)


def summary(df: pd.DataFrame) -> pd.DataFrame:
    def stats(g):
        a = g["diff"].abs()
        return pd.Series({
            "glasses": g["glass_id"].nunique(), "values": len(g),
            "within_0.05": f"{(a <= 0.05 + 1e-9).mean() * 100:.1f} %",
            "within_0.2": f"{(a <= 0.2 + 1e-9).mean() * 100:.1f} %",
            "median_abs": round(float(a.median()), 3),
            "p95_abs": round(float(np.percentile(a, 95)), 3),
            "max_abs": round(float(a.max()), 2)})
    return df.groupby(["source_id", "basis"]).apply(stats, include_groups=False)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worst", type=int, default=0)
    args = ap.parse_args()
    db = GlassDatabase.load()
    df = compare(db)
    pd.set_option("display.width", 200)
    print(summary(df).to_string())
    if args.worst:
        print(df.reindex(df["diff"].abs().sort_values(ascending=False).index)
              .head(args.worst).to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
