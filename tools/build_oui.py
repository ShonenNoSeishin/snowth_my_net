"""Regenerate the embedded IEEE vendor database (src/snowth_my_net/enrich/data/oui.tsv.gz).

    python tools/build_oui.py                 # download from the IEEE
    python tools/build_oui.py DIR             # use oui.csv, mam.csv, oui36.csv from DIR
"""

import sys
from pathlib import Path

from snowth_my_net.config.schema import OuiCfg
from snowth_my_net.enrich.oui import update_database

DEST = (Path(__file__).resolve().parents[1] / "src" / "snowth_my_net" / "enrich" / "data"
        / "oui.tsv.gz")

if __name__ == "__main__":
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    count = update_database(DEST, OuiCfg().urls, source)
    print(f"{DEST}: {count} prefixes, {DEST.stat().st_size} bytes")
