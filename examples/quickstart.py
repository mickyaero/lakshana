"""Lakshana quickstart — schemas for the bundled synthetic 5-type set.

Runs in under a minute on a laptop with a Groq API key:

    pip install lakshana[openai]
    export GROQ_API_KEY=...
    python examples/quickstart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Lets the example run from a fresh checkout without `pip install -e .`
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import lakshana

DOCS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "data" / "synthetic" / "documents"


def main() -> int:
    files = sorted(str(p) for p in DOCS_DIR.glob("*.txt"))
    if not files:
        print(f"no documents found under {DOCS_DIR}", file=sys.stderr)
        return 1

    print(f"discovering schemas in {len(files)} documents...")
    result = lakshana.discover(files=files, min_cluster_size=3)

    print()
    print(f"found {len(result.clusters)} document type(s):")
    for cluster in result.clusters:
        cid = str(cluster["id"])
        schema = result.schemas.get(cid, {})
        fields = [f["name"] for f in schema.get("fields", [])]
        print(f"  • {cluster.get('name', '?'):<20} ({cluster['doc_count']} docs)")
        for name in fields[:6]:
            print(f"      - {name}")
        if len(fields) > 6:
            print(f"      ... and {len(fields) - 6} more fields")

    return 0


if __name__ == "__main__":
    sys.exit(main())
