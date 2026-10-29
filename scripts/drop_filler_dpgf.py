"""Remove dPgF = 0 values that are a catalog's "not given" filler.

Applies glassmatch.importers.agf.zero_dpgf_verdicts - the check every .agf
import now runs - to the committed normalized tables, one source catalog at
a time, so data merged before the check existed gets the same treatment
without re-running the whole merge. Each dropped value is noted in the
glass's description. Idempotent: a second run finds nothing to drop.

    python scripts/drop_filler_dpgf.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from glassmatch.importers.agf import zero_dpgf_verdicts  # noqa: E402

NORM = ROOT / "data" / "normalized"


def main() -> None:
    read = {"dtype": str, "keep_default_na": False, "encoding": "utf-8"}
    props = pd.read_csv(NORM / "properties.csv", **read)
    sell = pd.read_csv(NORM / "sellmeier.csv", **read)
    glasses = pd.read_csv(NORM / "glasses.csv", **read)
    sell_rows = sell.replace("", None)

    drop_idx, notes = [], {}
    for sid, part in props.groupby("source_id"):
        ids = set(part["glass_id"])
        verdicts = zero_dpgf_verdicts(
            part.to_dict(orient="records"),
            sell_rows[sell_rows["glass_id"].isin(ids)].to_dict(orient="records"))
        for gid, (keep, _, why) in verdicts.items():
            if keep:
                continue
            hit = part[(part["glass_id"] == gid) & (part["property"] == "dPgF")
                       & (part["value"].astype(float) == 0.0)]
            drop_idx += list(hit.index)
            notes[gid] = f"ED dPgF 0 not stored: {why}, so the 0 reads as 'not given'."

    if not drop_idx:
        print("No filler dPgF values found.")
        return
    props = props.drop(index=drop_idx)
    for i, gid in glasses["glass_id"].items():
        if gid in notes and notes[gid] not in glasses.at[i, "description"]:
            glasses.at[i, "description"] = (
                glasses.at[i, "description"] + " " + notes[gid]).strip()
    props.to_csv(NORM / "properties.csv", index=False, lineterminator="\n")
    glasses.to_csv(NORM / "glasses.csv", index=False, lineterminator="\n")
    print(f"Dropped {len(drop_idx)} filler dPgF value(s) from {len(notes)} glass(es).")


if __name__ == "__main__":
    main()
