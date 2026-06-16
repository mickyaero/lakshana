"""Export discovered schemas as standard JSON Schema documents.

Use case: you want the inferred shape as a typed contract you can drop into
your extraction pipeline, OpenAPI spec, or LLM tool definition.

    pip install lakshana[openai]
    export GROQ_API_KEY=...
    python examples/export_json_schema.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import lakshana

DOCS_DIR = Path(__file__).resolve().parent.parent / "benchmarks" / "data" / "synthetic" / "documents"


def main() -> int:
    files = sorted(str(p) for p in DOCS_DIR.glob("*.txt"))[:25]  # subset for speed
    result = lakshana.discover(files=files, min_cluster_size=3)

    for cluster in result.clusters:
        cid = str(cluster["id"])
        schema = result.schemas.get(cid, {})
        name = cluster.get("name", f"cluster_{cid}")

        json_schema = lakshana.export_as_json_schema(schema, name=name)
        print(f"\n=== {name} ({cluster['doc_count']} docs) ===")
        print(json.dumps(json_schema, indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
