# CDGM — download the catalog data yourself; GlassMatch only ships the parser.
# 1. Visit https://www.cdgmgd.com/go.htm?k=ge_lei_xia_zai&url=downList (Downloads, 各类下载)
# 2. Download "zemax格式文档" (CDGM-ZEMAX202609.AGF as of 2026-10).
# 3. Save it to data/staging/official/cdgm/ and run `python scripts/merge_agf.py --all`,
#    or use Import/Export -> .agf in the app.
# License: redistribution-limited; the file stays on your machine.
