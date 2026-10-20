# SUMITA — download the catalog data yourself; GlassMatch only ships the parser.
# 1. Visit https://www.sumita-opt.co.jp/en/download/
# 2. Under Optical Glass Data, select "Zemax (all glasses including the discontinued ones)"
#    and download (a zip containing zemax.agf; 2026-08-26 as of 2026-10).
# 3. Save the .agf as data/staging/official/sumita/SUMITA_20260826.agf and run
#    `python scripts/merge_agf.py --all`, or use Import/Export -> .agf in the app.
# License: redistribution-limited; the file stays on your machine.
