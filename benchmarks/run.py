"""In-process Discover benchmark on the 5-type synthetic dataset.

Runs ``lakshana.discover()`` directly (no HTTP server), compares the
predicted cluster assignments to the manifest's ground-truth ``doc_type``,
and prints ARI / NMI / V-measure / purity.

Usage::

    python benchmarks/run.py
    python benchmarks/run.py --model groq/llama-3.3-70b-versatile
    python benchmarks/run.py --model claude-sonnet-4-6 --output benchmarks/results.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
# Allow running from a fresh checkout without `pip install -e .` or PYTHONPATH.
sys.path.insert(0, str(_HERE))                  # benchmarks/ for `metrics`
sys.path.insert(0, str(_HERE.parent / "src"))   # src/ for `lakshana`

import lakshana  # noqa: E402
from metrics import clustering_metrics, format_clustering_report  # noqa: E402

DOC_TYPE_MAP = {"invoice": 0, "memo": 1, "contract": 2, "resume": 3, "report": 4}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lakshana discover benchmark.")
    parser.add_argument(
        "--model", "-m",
        default="groq/llama-3.3-70b-versatile",
        help="LLM model id (default: groq/llama-3.3-70b-versatile).",
    )
    parser.add_argument(
        "--min-cluster-size", "-k", type=int, default=3,
        help="Minimum cluster size (default: 3).",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write full result JSON to this file.",
    )
    args = parser.parse_args(argv)

    here = Path(__file__).resolve().parent
    manifest_path = here / "data" / "synthetic" / "manifest.json"
    docs_dir = here / "data" / "synthetic" / "documents"

    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text())
    files: list[str] = []
    true_labels: list[int] = []
    for sample in manifest:
        p = docs_dir / sample["filename"]
        if p.exists():
            files.append(str(p))
            true_labels.append(DOC_TYPE_MAP[sample["doc_type"]])

    print(f"running discover on {len(files)} docs with {args.model}...", file=sys.stderr)
    t0 = time.time()
    result = lakshana.discover(
        files=files,
        model=args.model,
        min_cluster_size=args.min_cluster_size,
    )
    elapsed = time.time() - t0

    pred_labels = list(result.doc_cluster_ids[: len(true_labels)])
    true_labels = true_labels[: len(pred_labels)]

    metrics = clustering_metrics(pred_labels, true_labels)
    print()
    print(format_clustering_report(metrics))
    print()
    print(f"elapsed: {elapsed:.1f}s")
    print(f"clusters discovered:")
    for c in result.clusters:
        print(f"  {c['id']}: {c.get('name', '?')} ({c.get('doc_count', '?')} docs)")

    if args.output:
        full = {
            "model": args.model,
            "n_documents": len(files),
            "elapsed_seconds": round(elapsed, 2),
            "clustering": metrics,
            "clusters": [
                {
                    "id": c["id"],
                    "name": c.get("name", ""),
                    "doc_count": c.get("doc_count", 0),
                    "schema_fields": len(result.schemas.get(str(c["id"]), {}).get("fields", [])),
                }
                for c in result.clusters
            ],
        }
        Path(args.output).write_text(json.dumps(full, indent=2))
        print(f"\nwrote {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
