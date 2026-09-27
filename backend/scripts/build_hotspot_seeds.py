"""
Pre-build the static hotspot grid (DEM terrain + OpenStreetMap drains, roads,
facilities) for every monitored city and store it compressed under
app/data/hotspots/. A deployment then only fetches the live 3x3 rain lattice,
not ~256 elevations and a heavy Overpass query per city.

Resumable: cities that already have a seed with OSM data are skipped.

    python scripts/build_hotspot_seeds.py            # all cities
    python scripts/build_hotspot_seeds.py patna pune # some
"""

from __future__ import annotations

import asyncio
import gzip
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import hotspots  # noqa: E402
from app.engine import LOCATIONS  # noqa: E402

PAUSE_S = 6.0


WORKERS = 3


async def build_one(i: int, total: int, lid: str, counts: dict) -> None:
    seed = hotspots.SEED_DIR / f"{lid}.json.gz"
    if seed.exists():
        with gzip.open(seed, "rt", encoding="utf-8") as fh:
            if json.load(fh).get("osm_ok"):
                return
    # A local cache built while Overpass failed would be returned as-is.
    cache = hotspots.CACHE_DIR / f"{lid}.json"
    if cache.exists() and not json.loads(cache.read_text(encoding="utf-8")).get("osm_ok"):
        cache.unlink()
    t = time.time()
    try:
        static = await hotspots.build_static(lid, use_seed=False, budget_s=None)
    except Exception as exc:
        counts["failed"] += 1
        print(f"[{i}/{total}] {lid}: FAILED {str(exc)[:120]}", flush=True)
        return
    if not static.get("osm_ok"):
        counts["failed"] += 1
        print(f"[{i}/{total}] {lid}: OpenStreetMap unavailable, will retry", flush=True)
        return
    with gzip.open(seed, "wt", encoding="utf-8", compresslevel=9) as fh:
        json.dump(static, fh, separators=(",", ":"))
    counts["done"] += 1
    print(f"[{i}/{total}] {lid}: ok {time.time() - t:.0f}s {seed.stat().st_size // 1024} KB", flush=True)


async def main(ids: list[str]) -> None:
    hotspots.SEED_DIR.mkdir(parents=True, exist_ok=True)
    counts = {"done": 0, "failed": 0}
    sem = asyncio.Semaphore(WORKERS)

    async def guarded(i: int, lid: str) -> None:
        async with sem:
            await build_one(i, len(ids), lid, counts)
            await asyncio.sleep(PAUSE_S)

    await asyncio.gather(*(guarded(i, lid) for i, lid in enumerate(ids, 1)))
    print(f"built {counts['done']}, failed {counts['failed']}", flush=True)


if __name__ == "__main__":
    wanted = sys.argv[1:] or [l["id"] for l in LOCATIONS]
    for attempt in range(1, 4):
        print(f"--- pass {attempt}", flush=True)
        asyncio.run(main(wanted))
        missing = []
        for lid in wanted:
            seed = hotspots.SEED_DIR / f"{lid}.json.gz"
            ok = False
            if seed.exists():
                with gzip.open(seed, "rt", encoding="utf-8") as fh:
                    ok = bool(json.load(fh).get("osm_ok"))
            if not ok:
                missing.append(lid)
        print(f"--- after pass {attempt}: {len(missing)} missing {missing}", flush=True)
        if not missing:
            break
        wanted = missing
        time.sleep(120)
