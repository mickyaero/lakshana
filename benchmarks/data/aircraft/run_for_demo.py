"""Run lakshana.discover() on aircraft set and dump the full result as JSON
shaped exactly the way docstruct's discover.html consumes it (so the replica
demo page can render it without modification).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent.parent.parent
sys.path.insert(0, str(_REPO / "src"))

import lakshana  # noqa: E402

MANIFEST = _HERE / "manifest.json"
DOCS_DIR = _HERE / "documents"
OUT = _REPO / "site" / "demo" / "data.json"


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    files = [str(DOCS_DIR / m["filename"]) for m in manifest]
    print(f"running discover on {len(files)} aircraft documents...", file=sys.stderr)

    def progress(stage, msg, pct):
        print(f"  [{pct:3d}%] {stage:>10} | {msg}", file=sys.stderr)

    t0 = time.time()
    result = lakshana.discover(
        files=files,
        model="openai/gpt-4o-mini",
        min_cluster_size=3,
        on_progress=progress,
    )
    elapsed = time.time() - t0

    # Read snippets directly (the runtime stores first 500 chars per doc)
    payload = {
        "model": "openai/gpt-4o-mini",
        "elapsed_seconds": round(elapsed, 2),
        "stats": result.stats,
        "clusters": result.clusters,
        "schemas": result.schemas,
        "umap_coords": result.umap_coords,
        "umap_3d": result.umap_3d,
        "doc_names": [Path(f).name for f in result.doc_names],
        "doc_snippets": result.doc_snippets,
        "doc_cluster_ids": list(result.doc_cluster_ids),
        "ground_truth": [m["doc_type"] for m in manifest],
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, default=str, indent=2))
    print(f"\nwrote {OUT}  ({OUT.stat().st_size:,} bytes, {elapsed:.1f}s)", file=sys.stderr)
    print(f"clusters discovered:", file=sys.stderr)
    for c in result.clusters:
        cid = str(c["id"])
        nfields = len(result.schemas.get(cid, {}).get("fields", []))
        print(f"  {c.get('name', '?')!r} — {c['doc_count']} docs, {nfields} fields", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
