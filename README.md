# Lakshana

> **लक्षण** *(lakṣaṇa, Sanskrit)* — "defining characteristic, marker, distinguishing feature."

**Zero-config schema discovery for document collections.** Drop a folder of PDFs, get a JSON Schema. No training, no labels, no manual schema design.

```bash
pip install lakshana
export GROQ_API_KEY=...
lakshana analyze ./my_docs --output schema.json
```

---

## What it does

Given a folder of mixed documents — invoices, contracts, statements, forms — Lakshana figures out:

1. **What document *types* are in there** (clusters similar docs together via UMAP + HDBSCAN over a hybrid structural+semantic embedding).
2. **What *fields* each type has** (asks an LLM to infer a schema, then verifies field frequency across the cluster).
3. **A clean JSON Schema (or CSV headers, or Markdown table) per type** — ready to drive downstream extraction.

It's the "tell me what I have" step that every document-extraction pipeline skips — and pays for later.

## Highlights

- **Zero schema design.** Point it at a folder. Get back a typed schema with frequency and grounding for every field.
- **No labels, no training.** Pure clustering + LLM inference. Works on a dataset of 10 docs or 10,000.
- **CPU only.** No GPU required.
- **Multi-LLM.** Anthropic, OpenAI, Groq, Cerebras, Google, OpenRouter, Ollama. Bring whatever key you have.
- **Receipts.** 92% cluster purity on a synthetic 5-type benchmark (invoice / memo / contract / resume / report).
- **Interactive visualization out of the box.** 2D/3D UMAP scatter, schema editor, field-frequency lollipop charts.

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

## CLI

```bash
lakshana analyze ./docs --model groq/llama-3.3-70b-versatile --output result.json
```

## Why it exists

Most "AI document extraction" tools assume *you* already know what fields you want. Real-world data is messier than that — you get a hard drive of receipts and contracts and `???` and you have to figure out the shape before you can extract anything.

Lakshana is the discovery step that lets the rest of your pipeline be simple. It started as a feature inside [docstruct](https://github.com/mickyaero/docstruct); it's now its own thing so anyone can use it.

— [Micky Droch](https://github.com/mickyaero)

## License

MIT — use it freely, including commercially. Attribution appreciated, not required.
