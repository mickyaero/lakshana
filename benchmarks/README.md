# Lakshana benchmarks

A small reproducibility harness for the clustering accuracy claim in the top-level README.

## Synthetic 5-type benchmark

`data/synthetic/` contains 50 documents — 10 each of `invoice`, `memo`, `contract`, `resume`, `report` — with ground-truth labels in `manifest.json`. The benchmark runs `lakshana.discover()` over the folder and compares predicted cluster assignments to the manifest's `doc_type`.

```bash
# Default: free Groq tier (set GROQ_API_KEY)
python benchmarks/run.py

# Anthropic
ANTHROPIC_API_KEY=... python benchmarks/run.py --model claude-sonnet-4-6

# Persist full JSON
python benchmarks/run.py --output benchmarks/result.json
```

Metrics reported: Adjusted Rand Index, Normalized Mutual Information, V-measure, homogeneity, completeness, purity.

## Note on noise points

HDBSCAN can assign a small number of documents to the noise cluster (label `-1`). These are kept in the metrics — they count as a cluster of their own. That's the honest number.
