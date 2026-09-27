"""
Export the built 30-year GloFAS climatology to a compressed seed file.

A fresh deployment (e.g. Render's free plan, which has no persistent disk) loads
this seed on boot instead of rebuilding the baseline from Open-Meteo's archive,
which is slow and uses a large share of the shared-IP rate limit.

    python scripts/export_climatology.py
"""

from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import store  # noqa: E402
from app.config import DATA_DIR  # noqa: E402

SEED = DATA_DIR / "climatology_seed.json.gz"


def main() -> None:
    with store.db() as conn:
        rows = conn.execute(
            "SELECT location_id, built_at, start_year, end_year, lat, lon, stats FROM climatology"
        ).fetchall()
    out = [
        {
            "location_id": r["location_id"],
            "built_at": r["built_at"],
            "start_year": r["start_year"],
            "end_year": r["end_year"],
            "lat": r["lat"],
            "lon": r["lon"],
            "stats": json.loads(r["stats"]),
        }
        for r in rows
        if r["lat"] is not None
    ]
    with gzip.open(SEED, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(out, fh, separators=(",", ":"))
    print(f"wrote {len(out)} locations to {SEED} ({SEED.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
