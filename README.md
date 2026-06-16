# Lakshana

[![CI](https://github.com/mickyaero/lakshana/actions/workflows/test.yml/badge.svg)](https://github.com/mickyaero/lakshana/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%20|%203.11%20|%203.12-blue.svg)](pyproject.toml)

> **लक्षण** *(lakṣaṇa, Sanskrit)* — "defining characteristic, marker, distinguishing feature."

**Zero-config schema discovery for document collections.** Drop a folder of PDFs, get a JSON Schema. No training, no labels, no manual schema design.

```bash
pip install lakshana
export GROQ_API_KEY=...   # free tier works
lakshana analyze ./my_docs --output schema.json
```

---

## What it does

Given a folder of mixed documents — invoices, contracts, statements, forms — Lakshana figures out:

1. **What document *types* are in there.** Clusters similar docs together via UMAP + HDBSCAN over a hybrid structural+semantic embedding.
2. **What *fields* each type has.** Asks an LLM to infer a schema, then verifies field frequency across the cluster with grounding quotes.
3. **A clean JSON Schema (or CSV headers, or Markdown table) per type.** Ready to drive downstream extraction.

It's the "tell me what I have" step that every document-extraction pipeline skips — and pays for later.

## What you actually get

Real Groq Llama 3.3 70B run on 10 mixed docs (5 contracts + 5 invoices), captured verbatim:

```
cluster 0: 'Service Agreement'  (5 docs)
  fields:  provider, client, agreement_date, scope_of_services, compensation,
           term_start_date, term_end_date, payment_terms
  groups:  Contract Terms, Service Parties

cluster 1: 'Invoice'  (5 docs)
  fields:  invoice_number, date, bill_to, description, quantity, price,
           tax_amount, total_amount
  groups:  Invoice Line Items, Invoice Metadata, Tax & Totals
```

- **100% cluster purity** vs. ground truth labels
- **107 seconds** end-to-end (clustering + LLM schema discovery + frequency verification + semantic grouping)
- **$0** with the free Groq tier

## Highlights

- **Zero schema design.** Point it at a folder. Get back a typed schema with frequency and grounding for every field.
- **No labels, no training.** Pure clustering + LLM inference. Works on a dataset of 10 docs or 10,000.
- **CPU only.** No GPU required.
- **Multi-LLM.** Anthropic, OpenAI, Groq, Cerebras, Google, OpenRouter, Ollama. Bring whatever key you have.
- **India-first by accident.** Born inside a stack focused on Indian financial documents — the bundled BFSI benchmark covers 7 doc types including GST invoices, Form 26AS, ITR, and KYC.
- **77 unit tests, CI green** on Python 3.10 / 3.11 / 3.12.

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

Export formats:

```python
from lakshana import export_as_json_schema, export_as_csv_headers, export_as_markdown

schema = result.schemas["0"]
json_schema_doc = export_as_json_schema(schema, name="Invoice")  # standard JSON Schema
csv_header_row  = export_as_csv_headers(schema)                  # spreadsheet headers
markdown_table  = export_as_markdown(schema, name="Invoice")     # docs / wiki
```

## CLI

```bash
lakshana analyze ./docs --model groq/llama-3.3-70b-versatile --output result.json
```

## Run the benchmarks yourself

The claims above aren't marketing numbers — they're reproducible from a fresh clone:

```bash
git clone https://github.com/mickyaero/lakshana && cd lakshana
export GROQ_API_KEY=...

# 50 docs across 5 generic types (invoice/memo/contract/resume/report)
python benchmarks/run.py --dataset synthetic

# 35 Indian financial docs across 7 types (GST invoice, ITR, 26AS, KYC, bank stmt, loan, insurance)
python benchmarks/run.py --dataset bfsi
```

Reports ARI, NMI, V-measure, homogeneity, completeness, and cluster purity. See [`benchmarks/README.md`](benchmarks/README.md).

## Examples

- [`examples/quickstart.py`](examples/quickstart.py) — discover schemas across the bundled dataset and print fields per cluster.
- [`examples/export_json_schema.py`](examples/export_json_schema.py) — export each cluster as a standard JSON Schema for downstream extraction / OpenAPI specs / LLM tool contracts.

## How it works

```
parse → embed (structural + semantic)
     → cluster (UMAP + HDBSCAN)
     → label cluster (LLM)
     → infer schema (LLM)
     → verify field frequency across the cluster (LLM + grounding)
     → deduplicate + group fields semantically
     → export (JSON Schema / CSV / Markdown)
```

Every step has a graceful fallback. Every output is from real text in your documents, not a hallucination — fields ship with `frequency`, `doc_count`, and `verified_against` so you can see exactly how trustworthy each one is.

## Why it exists

Most "AI document extraction" tools assume *you* already know what fields you want. Real-world data is messier than that — you get a hard drive of receipts and contracts and `???` and you have to figure out the shape before you can extract anything.

Lakshana is the discovery step that lets the rest of your pipeline be simple. It started as a feature inside [docstruct](https://github.com/mickyaero/docstruct); it's now its own thing so anyone can use it.

— [Micky Droch](https://github.com/mickyaero)

## Contributing

Issues and PRs welcome. Especially:

- New LLM provider integrations (add to `src/lakshana/llm.py`)
- Real-world benchmark datasets (please anonymize before sharing)
- Examples in other domains (medical, legal, scientific)

`pip install -e ".[dev]" && pytest` to develop locally.

## License

MIT — use it freely, including commercially. Attribution appreciated, not required.
