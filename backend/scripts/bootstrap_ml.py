"""
One-shot ML bootstrap: fill any missing climatology, then train the classifier.

    python backend/scripts/bootstrap_ml.py

Safe to re-run: climatology skips locations that already have a valid baseline,
and train_model.py resumes from its per-date archive cache.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import store  # noqa: E402
from app.engine import LOCATIONS, engine  # noqa: E402


async def fill_climatology() -> None:
    store.init_db()
    built = await engine.ensure_climatology()
    print(f"climatology: built {built}, now {len(engine.climatology)}/{len(LOCATIONS)}", flush=True)


if __name__ == "__main__":
    asyncio.run(fill_climatology())
    sys.exit(subprocess.call([sys.executable, "-u", str(ROOT / "scripts" / "train_model.py")]))
