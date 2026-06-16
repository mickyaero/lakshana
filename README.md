# Lakshana

[![PyPI](https://img.shields.io/pypi/v/lakshana.svg)](https://pypi.org/project/lakshana/)
[![CI](https://github.com/mickyaero/lakshana/actions/workflows/test.yml/badge.svg)](https://github.com/mickyaero/lakshana/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue.svg)](pyproject.toml)

> **लक्षण** *(lakṣaṇa, Sanskrit)* — "defining characteristic, marker, distinguishing feature."

**Zero-config schema discovery for document collections.** Point Lakshana at a folder of mixed documents and it returns a JSON Schema for each document type it finds. No training, no labels, no manual schema design.

```bash
pip install "lakshana[openai]"      # or [anthropic] · [google] · [all]

export OPENAI_API_KEY=...           # or GROQ / ANTHROPIC / CEREBRAS / GOOGLE
lakshana analyze ./my_docs --output schema.json
```

There's also an [interactive demo](https://mickyaero.github.io/lakshana/demo/) that walks through a real run, end to end, in the browser.

---

## What it does

Given a folder of mixed documents — invoices, contracts, statements, forms, reports — Lakshana figures out:

1. **What document types are in there.** Clusters similar documents together via UMAP + HDBSCAN over a hybrid structural + semantic embedding.
2. **What fields each type has.** Asks an LLM to infer a schema, then verifies field frequency across the cluster with grounding quotes.
3. **A clean schema per type, in the format you want.** JSON Schema, CSV headers, Markdown table, or a structured entity list — ready to drive downstream extraction.

It is the *"tell me what I have"* step that every document-extraction pipeline skips — and pays for later.

## Highlights

- **Zero schema design.** Point it at a folder. Get back a typed schema with frequency and grounding for every field.
- **No labels, no training.** Pure clustering plus LLM inference. Works on 10 documents or 10,000.
- **Runs anywhere.** CPU is enough on a laptop; GPU is supported but not required.
- **Bring your own LLM.** Anthropic, OpenAI, Groq, Cerebras, Google, OpenRouter, Ollama, or any OpenAI-compatible endpoint.
- **Mixed structured + prose.** Works on form-style key-value documents *and* on prose narrative — the schema comes from both.
- **Tested.** 77 unit tests, CI green on Python 3.10 / 3.11 / 3.12.

## Python API

```python
from lakshana import discover

result = discover(
    files=["./docs/inv1.pdf", "./docs/inv2.pdf", "./docs/contract.pdf"],
    model="groq/llama-3.3-70b-versatile",
    min_cluster_size=3,
)

for cluster in result.clusters:
    schema = result.schemas[str(cluster["id"])]
    print(cluster["name"], "→", [f["name"] for f in schema["fields"]])
```

Each field on the returned schema carries `frequency`, `doc_count`, and `verified_against` so you can see exactly how trustworthy it is.

Export the result in whichever format fits your downstream pipeline:

```python
from lakshana import (
    export_as_json_schema,
    export_as_csv_headers,
    export_as_markdown,
)

schema = result.schemas["0"]
export_as_json_schema(schema, name="Invoice")   # standard JSON Schema
export_as_csv_headers(schema)                    # spreadsheet headers
export_as_markdown(schema, name="Invoice")       # documentation / wiki
```

## CLI

```bash
lakshana analyze ./docs --model groq/llama-3.3-70b-versatile --output result.json
```

## How it works

```
parse → embed (structural + semantic)
     → cluster (UMAP + HDBSCAN)
     → label cluster (LLM)
     → infer schema (LLM)
     → verify field frequency across the cluster (LLM + grounding)
     → deduplicate and group fields semantically
     → export (JSON Schema / CSV / Markdown)
```

Every step has a graceful fallback. Every output traces back to real text in your documents.

## Benchmarks

The repo ships with two reproducible benchmarks. Clone, set an API key, and run:

```bash
git clone https://github.com/mickyaero/lakshana && cd lakshana
export GROQ_API_KEY=...

python benchmarks/run.py --dataset synthetic   # 50 docs, 5 generic types
python benchmarks/run.py --dataset bfsi        # 35 Indian financial docs, 7 types
```

Reports ARI, NMI, V-measure, homogeneity, completeness, and cluster purity. See [`benchmarks/README.md`](benchmarks/README.md).

## Examples

- [`examples/quickstart.py`](examples/quickstart.py) — discover schemas across the bundled dataset and print fields per cluster.
- [`examples/export_json_schema.py`](examples/export_json_schema.py) — export each cluster as a standard JSON Schema for downstream extraction, OpenAPI specs, or LLM tool contracts.

## Why it exists

Most AI document-extraction tools assume *you* already know what fields you want. Real-world data isn't shaped that way — you get a hard drive of receipts, contracts, statements, and `???`, and you have to figure out the shape before you can extract anything.

Lakshana is the discovery step that lets the rest of your pipeline be simple.

— Micky · [@mickyaero](https://github.com/mickyaero)

## Contributing

Issues and PRs welcome. Especially:

- New LLM provider integrations (add to `src/lakshana/llm.py`)
- Real-world benchmark datasets (please anonymize before sharing)
- Examples in other domains (medical, legal, scientific)

`pip install -e ".[dev]" && pytest` to develop locally.

## License

MIT — use it freely, including commercially.
