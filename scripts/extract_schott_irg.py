"""Extract the refractive-index tables of SCHOTT's IRG datasheets.

    python scripts/extract_schott_irg.py

SCHOTT's infrared chalcogenide glass datasheets (IRG 22, 24, 25, 26, 27;
versions July / September 2018, from schott.com > Infrared glasses and materials >
Downloads) print n at 22 C and absolute dn/dT at 0.85-12 um. The .agf SCHOTT
publishes for the same glasses gives no catalog n_d, so these tables are what
its dispersion fits are verified against (scripts/verify_ir_dispersion.py).
The PDFs stay in data/staging/official/schott_ir/ (redistribution-limited);
only the extracted numbers, with their source, are written to
data/validation/schott_irg_datasheets.csv.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGED = ROOT / "data" / "staging" / "official" / "schott_ir"
OUT = ROOT / "data" / "validation" / "schott_irg_datasheets.csv"
SOURCE = "SCHOTT-IRG-DATASHEETS-2018"
# dn/dT is "–" when not given, and negative values use a typographic minus,
# sometimes spaced: "– 1.0", "–3.6".
ROW = re.compile(r"^(\d+(?:\.\d+)?) ([23]\.\d{4}) (–|-|[–-]?\s*\d+(?:\.\d+)?)$")


def main() -> int:
    import pypdf
    rows = []
    for pdf in sorted(STAGED.glob("irg*.pdf")):
        m = re.fullmatch(r"irg(\d+)", pdf.stem)
        if not m:
            continue
        text = "\n".join(p.extract_text() for p in pypdf.PdfReader(pdf).pages)
        ver = re.search(r"Version (\w+ \d{4})", text)
        if ver is None:
            print(f"{pdf.name}: no version line - check before use")
            return 1
        gid = f"SCHOTT-IRG{m.group(1)}"
        got = 0
        for line in text.splitlines():
            r = ROW.match(line.strip())
            if r:
                d = r.group(3).replace("–", "-").replace(" ", "")
                rows.append({"glass_id": gid, "wavelength_um": float(r.group(1)),
                             "n_22c": float(r.group(2)),
                             "dn_dt_abs_1e6_per_k": "" if d == "-" else float(d),
                             "source_id": SOURCE,
                             "document": f"SCHOTT Infrared Chalcogenide Glass IRG "
                                         f"{m.group(1)} datasheet, version {ver.group(1)}"})
                got += 1
        print(f"{pdf.name}: {got} index rows")
    if not rows:
        print("nothing extracted - are the datasheets staged?")
        return 1
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
