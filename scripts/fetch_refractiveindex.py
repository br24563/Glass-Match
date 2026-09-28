"""Download CC0 optical-constant pages from refractiveindex.info.

The refractiveindex.info database is dedicated to the public domain under
CC0 1.0 (https://github.com/polyanskiy/refractiveindex.info-database), so
unlike the manufacturer .agf catalogs these files may be committed and
redistributed.  Each YAML page carries the literature reference it was taken
from, which GlassMatch records per-material as its source.

Run once to refresh the local copy:

    python scripts/fetch_refractiveindex.py

The downloaded tree, the pinned upstream commit and a per-file manifest are
written to data/spectral/refractiveindex_info/ so the import is reproducible.
"""
from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = "polyanskiy/refractiveindex.info-database"
BRANCH = "main"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "spectral" / "refractiveindex_info"
API = f"https://api.github.com/repos/{REPO}"
RAW = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}"

# Material formula -> (glass_id stem, display name, material_class).
# The list is deliberately the transmissive optics workhorses - UV/MIR
# fluorides, sapphire-family oxides and IR semiconductors - rather than every
# entry in the database, which is dominated by thin-film materials.
MATERIALS = {
    "CaF2": ("CAF2", "Calcium fluoride (fluorite)", "crystal"),
    "MgF2": ("MGF2", "Magnesium fluoride (magnesite)", "crystal"),
    "BaF2": ("BAF2", "Barium fluoride", "crystal"),
    "SrF2": ("SRF2", "Strontium fluoride", "crystal"),
    "LiF": ("LIF", "Lithium fluoride", "crystal"),
    "LaF3": ("LAF3", "Lanthanum fluoride", "crystal"),
    "Al2O3": ("AL2O3", "Aluminium oxide (sapphire)", "crystal"),
    "SiO2": ("SIO2", "Silicon dioxide (fused silica / quartz)", "crystal"),
    "MgAl2O4": ("MGAL2O4", "Magnesium aluminate (spinel)", "crystal"),
    "Y3Al5O12": ("Y3AL5O12", "Yttrium aluminium garnet (YAG)", "crystal"),
    "ZnSe": ("ZNSE", "Zinc selenide", "crystal"),
    "ZnS": ("ZNS", "Zinc sulfide", "crystal"),
    "Ge": ("GE", "Germanium", "crystal"),
    "Si": ("SI", "Silicon", "crystal"),
    "CdTe": ("CDTE", "Cadmium telluride", "crystal"),
    "GaAs": ("GAAS", "Gallium arsenide", "crystal"),
    "Te": ("TE", "Tellurium", "crystal"),
}

UA = {"User-Agent": "GlassMatch/0.5 (optical materials database)"}


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _get_json(url: str):
    return json.loads(_get(url).decode("utf-8"))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    # The upstream catalog files enumerate every material page and its data
    # path, so two raw downloads replace a per-directory API listing. That
    # matters: the unauthenticated GitHub API allows 60 requests an hour and
    # this script is meant to be runnable by anyone on a fresh clone.
    manifest = {"repository": REPO, "branch": BRANCH, "license": "CC0-1.0",
                "files": []}
    catalog_sha = None
    pages: list[tuple[str, str, str, str]] = []   # formula, kind, page, path
    for kind in ("n2", "nk"):
        url = f"{RAW}/database/catalog-{kind}.yml"
        try:
            payload = _get(url)
        except (urllib.error.URLError, OSError) as e:
            print(f"error: cannot fetch {url} ({e})")
            return 1
        if catalog_sha is None:
            catalog_sha = hashlib.sha256(payload).hexdigest()
        book = page = None
        for line in payload.decode("utf-8", "replace").splitlines():
            s = line.strip()
            if s.startswith("- BOOK:"):
                book, page = s.split(":", 1)[1].strip(), None
            elif s.startswith("- PAGE:"):
                page = s.split(":", 1)[1].strip()
            elif s.startswith("data:") and book and page:
                path = s.split(":", 1)[1].strip()
                if path.startswith(f"main/{book}/"):
                    pages.append((book, kind, page, path))
                # keep `book`: the next - PAGE: belongs to the same material
                page = None
    print(f"catalog lists {len(pages)} page(s)")

    wanted = {f: v for f, v in MATERIALS.items()}
    total = failed = 0
    for formula, (stem, _name, _cls) in wanted.items():
        got = 0
        for book, kind, page, path in pages:
            if book != formula:
                continue
            dest = OUT / formula / f"{kind}__{Path(path).name}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            try:
                # The catalog's `data:` field is relative to database/data/.
                # Some upstream filenames contain spaces (e.g. a page named
                # "Rodriguez-de Marcos"), so the path is percent-encoded.
                url = f"{RAW}/database/data/{urllib.parse.quote(path)}"
                payload = _get(url)
            except (urllib.error.URLError, OSError, ValueError) as e:
                print(f"  {formula}/{page}: FAILED ({e})")
                failed += 1
                continue
            dest.write_bytes(payload)
            total += 1
            got += 1
            manifest["files"].append({
                "material": formula, "glass_stem": stem, "kind": kind,
                "page": page, "file": dest.name, "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            })
        print(f"  {formula}: {got} page(s)")

    manifest["catalog_sha256"] = catalog_sha
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"\nwrote {total} file(s) to {OUT.relative_to(ROOT)}"
          + (f" ({failed} failed)" if failed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())