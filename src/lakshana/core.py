"""Lakshana core: analyze document collections to discover implicit schemas.

Pipeline: parse → embed → cluster (UMAP + HDBSCAN) → discover schema (LLM) → verify frequency → export.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from lakshana.llm import call_llm
from lakshana.ingest import extract_text_from_file

logger = logging.getLogger(__name__)


@dataclass
class DiscoverResult:
    """Result of template discovery."""
    clusters: list[dict] = field(default_factory=list)
    schemas: dict = field(default_factory=dict)
    umap_coords: list[list[float]] = field(default_factory=list)
    umap_3d: list[list[float]] = field(default_factory=list)
    doc_names: list[str] = field(default_factory=list)
    doc_snippets: list[str] = field(default_factory=list)
    doc_cluster_ids: list[int] = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    logs: list[str] = field(default_factory=list)
    embeddings: np.ndarray | None = field(default=None, repr=False)


# --- Structural Fingerprinting ---

_DATE_RE = re.compile(r'\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b|\b\d{4}[/\-]\d{2}[/\-]\d{2}\b|\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+\d{1,2},?\s+\d{4}\b', re.I)
_AMOUNT_RE = re.compile(r'[\$€£¥]\s*[\d,]+\.?\d*|\b\d{1,3}(?:,\d{3})+(?:\.\d{2})?\b')
_EMAIL_RE = re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.-]+\b')
_PHONE_RE = re.compile(r'\b(?:\+?\d{1,3}[\s\-]?)?\(?\d{2,4}\)?[\s\-]?\d{3,4}[\s\-]?\d{3,4}\b')
_URL_RE = re.compile(r'https?://\S+')
_KV_RE = re.compile(r'^(.{2,40})\s*[:=]\s*(.+)$', re.MULTILINE)
_HEADER_RE = re.compile(r'^(?:#{1,4}\s+.+|[A-Z][A-Z\s]{2,40}$)', re.MULTILINE)


def structural_fingerprint(text: str) -> list[float]:
    """Extract structural features from a document for clustering.

    Returns an 18-dimensional vector summarising:
      sizes (chars, lines, words), density of dates / amounts / emails /
      phones / URLs / KV-pairs / headers / table-lines / paragraphs,
      and 6 binary 'has X' flags.

    Empty input returns a vector of zeros — earlier versions produced
    spurious 1.0 components for paragraphs because of a default
    division-by-1, which polluted the embedding space with phantom
    structure.
    """
    if not text:
        return [0.0] * 18

    features = []
    chars = len(text)
    lines = text.count('\n') + 1
    words = len(text.split())
    features.extend([
        min(chars / 10000, 5.0),
        min(lines / 100, 5.0),
        min(words / 2000, 5.0),
    ])

    features.extend([
        min(len(_DATE_RE.findall(text)) / max(lines, 1), 1.0),
        min(len(_AMOUNT_RE.findall(text)) / max(lines, 1), 1.0),
        min(len(_EMAIL_RE.findall(text)) / max(lines, 1), 1.0),
        min(len(_PHONE_RE.findall(text)) / max(lines, 1), 1.0),
        min(len(_URL_RE.findall(text)) / max(lines, 1), 1.0),
    ])

    kv_matches = _KV_RE.findall(text)
    features.append(min(len(kv_matches) / max(lines, 1), 1.0))

    headers = _HEADER_RE.findall(text)
    features.append(min(len(headers) / 10, 1.0))

    table_lines = sum(1 for line in text.split('\n') if line.count('\t') >= 2 or line.count('|') >= 2)
    features.append(min(table_lines / max(lines, 1), 1.0))

    # Only count paragraphs when the text actually contains paragraph
    # breaks; otherwise the default `\n\n`.count + 1 falsely returns 1.
    if '\n\n' in text:
        paragraphs = text.count('\n\n') + 1
        features.append(min(paragraphs / max(lines, 1), 1.0))
    else:
        features.append(0.0)

    # Binary flags
    has_date = 1.0 if _DATE_RE.search(text) else 0.0
    has_amount = 1.0 if _AMOUNT_RE.search(text) else 0.0
    has_email = 1.0 if _EMAIL_RE.search(text) else 0.0
    has_table = 1.0 if table_lines > 0 else 0.0
    has_headers = 1.0 if len(headers) > 0 else 0.0
    has_kv = 1.0 if len(kv_matches) > 3 else 0.0
    features.extend([has_date, has_amount, has_email, has_table, has_headers, has_kv])

    return features


# --- Embedding ---

def embed_documents(texts: list[str], doc_names: list[str]) -> np.ndarray:
    """Generate hybrid embeddings (structural + semantic) for documents."""
    from lakshana._utils import get_embedding_model

    model = get_embedding_model()

    # Use more text for semantic embedding — first 512 tokens ~ 2000 chars
    # But also sample from middle and end for longer docs
    def _smart_truncate(t, max_len=2000):
        if len(t) <= max_len:
            return t
        third = max_len // 3
        return t[:third] + "\n...\n" + t[len(t)//2 - third//2 : len(t)//2 + third//2] + "\n...\n" + t[-third:]

    truncated = [_smart_truncate(t) for t in texts]
    semantic = model.encode(truncated, show_progress_bar=False, normalize_embeddings=True).astype("float32")

    structural = np.array([structural_fingerprint(t) for t in texts], dtype="float32")
    norms = np.linalg.norm(structural, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    structural = structural / norms

    combined = np.concatenate([structural * 0.6, semantic * 0.4], axis=1)
    return combined


# --- Clustering ---

def cluster_documents(embeddings: np.ndarray, min_cluster_size: int = 3) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Cluster documents using UMAP + HDBSCAN.

    Returns (cluster_labels, umap_2d_coords, umap_3d_coords).
    """
    import umap
    from sklearn.cluster import HDBSCAN

    n_docs = len(embeddings)

    if n_docs < 3:
        return (np.zeros(n_docs, dtype=int),
                np.random.randn(n_docs, 2).astype("float32"),
                np.random.randn(n_docs, 3).astype("float32"))

    n_neighbors = min(15, n_docs - 1)

    # Single UMAP to 3D — use for both visualization and clustering
    reducer_3d = umap.UMAP(
        n_components=min(3, n_docs - 1), n_neighbors=n_neighbors, min_dist=0.1,
        metric='cosine', random_state=42
    )
    umap_3d = reducer_3d.fit_transform(embeddings).astype("float32")
    if umap_3d.shape[1] < 3:
        umap_3d = np.pad(umap_3d, ((0, 0), (0, 3 - umap_3d.shape[1])))

    # 2D is just the first two dims of 3D (avoids running UMAP twice)
    umap_2d = umap_3d[:, :2].copy()

    if n_docs < 6:
        return np.zeros(n_docs, dtype=int), umap_2d, umap_3d

    # For clustering, use higher-dim UMAP if enough docs
    if n_docs >= 10:
        n_cluster_dims = min(15, n_docs - 2)
        reducer_cluster = umap.UMAP(
            n_components=max(n_cluster_dims, 2), n_neighbors=n_neighbors, min_dist=0.0,
            metric='cosine', random_state=42
        )
        umap_cluster = reducer_cluster.fit_transform(embeddings)
    else:
        umap_cluster = umap_3d

    min_cs = max(min_cluster_size, 2)
    clusterer = HDBSCAN(min_cluster_size=min_cs, min_samples=2, metric='euclidean')
    labels = clusterer.fit_predict(umap_cluster)

    # Assign outliers to nearest cluster
    if -1 in labels and len(set(labels) - {-1}) > 0:
        from sklearn.neighbors import NearestNeighbors
        cluster_mask = labels >= 0
        if cluster_mask.sum() > 0:
            nn = NearestNeighbors(n_neighbors=1, metric='euclidean')
            nn.fit(umap_cluster[cluster_mask])
            outlier_mask = labels == -1
            _, indices = nn.kneighbors(umap_cluster[outlier_mask])
            cluster_indices = np.where(cluster_mask)[0]
            labels[outlier_mask] = labels[cluster_indices[indices.flatten()]]

    if len(set(labels)) <= 1 and labels[0] == -1:
        labels = np.zeros(n_docs, dtype=int)

    return labels, umap_2d, umap_3d


# --- Sub-Cluster Detection ---

def detect_subclusters(embeddings: np.ndarray, labels: np.ndarray, min_size: int = 2) -> dict:
    """For clusters with > 8 documents, run a second HDBSCAN pass to find sub-clusters.

    Returns a dict mapping cluster_id -> list of sub-cluster dicts:
    {0: [{"name": "sub_0_0", "doc_indices": [1, 3, 5], "doc_count": 3}, ...]}
    """
    from sklearn.cluster import HDBSCAN

    subclusters = {}
    unique_labels = sorted(set(labels))
    if -1 in unique_labels:
        unique_labels.remove(-1)

    for cid in unique_labels:
        indices = np.where(labels == cid)[0]
        if len(indices) <= 8:
            continue

        cluster_embeddings = embeddings[indices]

        # Run HDBSCAN with smaller min_cluster_size for sub-clusters
        sub_min = max(min_size, 2)
        sub_clusterer = HDBSCAN(min_cluster_size=sub_min, min_samples=2, metric='euclidean')
        sub_labels = sub_clusterer.fit_predict(cluster_embeddings)

        unique_sub = sorted(set(sub_labels))
        if len(unique_sub) <= 1:
            continue  # No meaningful sub-clusters found

        subs = []
        for sid in unique_sub:
            if sid == -1:
                continue
            sub_indices = indices[np.where(sub_labels == sid)[0]]
            subs.append({
                "name": f"sub_{cid}_{sid}",
                "doc_indices": sub_indices.tolist(),
                "doc_count": len(sub_indices),
            })

        if len(subs) > 1:  # Only report if actually split into sub-groups
            subclusters[int(cid)] = subs

    return subclusters


# --- Cross-Cluster Field Linking ---

def find_cross_cluster_fields(schemas: dict) -> list[dict]:
    """Identify fields that appear across multiple clusters.

    Returns list of cross-cluster field records with cluster membership and avg frequency.
    """
    field_clusters = {}  # field_name -> list of {cluster_id, frequency}

    for cluster_id, schema in schemas.items():
        for fld in schema.get("fields", []):
            name = fld.get("name", "")
            if not name:
                continue
            norm = _normalize_field_name(name)
            if norm not in field_clusters:
                field_clusters[norm] = []
            field_clusters[norm].append({
                "cluster_id": cluster_id,
                "frequency": fld.get("frequency", 0),
            })

    # Only include fields that appear in 2+ clusters
    cross_fields = []
    for name, entries in field_clusters.items():
        if len(entries) < 2:
            continue
        avg_freq = sum(e["frequency"] for e in entries) / len(entries)
        cross_fields.append({
            "name": name,
            "clusters": [e["cluster_id"] for e in entries],
            "frequencies": {e["cluster_id"]: e["frequency"] for e in entries},
            "avg_frequency": round(avg_freq, 1),
        })

    cross_fields.sort(key=lambda x: x["avg_frequency"], reverse=True)
    return cross_fields


# --- Field Name Normalization ---

def _normalize_field_name(name: str) -> str:
    """Normalize field name to consistent snake_case."""
    n = name.strip()
    # camelCase → snake_case (MUST run before .lower())
    n = re.sub(r'([a-z])([A-Z])', r'\1_\2', n)
    n = n.lower()
    # Replace spaces, hyphens, dots with underscores
    n = re.sub(r'[\s\-\.]+', '_', n)
    # Remove non-alphanumeric except underscores
    n = re.sub(r'[^a-z0-9_]', '', n)
    # Collapse multiple underscores
    n = re.sub(r'_+', '_', n).strip('_')
    return n


def _merge_field_lists(existing: list[dict], new_fields: list[dict]) -> list[dict]:
    """Merge new fields into existing schema, deduplicating by normalized name."""
    merged = {}
    for f in existing:
        name = f.get("name", "")
        if not name:
            continue
        norm = _normalize_field_name(str(name))
        if norm:
            merged[norm] = f.copy()

    for f in new_fields:
        norm = _normalize_field_name(f.get("name", ""))
        if not norm:
            continue
        if norm in merged:
            # Update description if new one is longer/better
            if len(f.get("description", "")) > len(merged[norm].get("description", "")):
                merged[norm]["description"] = f["description"]
            # Collect examples
            if f.get("example") and f["example"] != merged[norm].get("example", ""):
                existing_ex = merged[norm].get("examples", [])
                if merged[norm].get("example"):
                    existing_ex = [merged[norm]["example"]] + existing_ex
                existing_ex.append(f["example"])
                merged[norm]["examples"] = list(set(existing_ex))[:5]
                merged[norm]["example"] = existing_ex[0]
            # Prefer more specific type
            if f.get("type") and f["type"] != "string" and merged[norm].get("type") == "string":
                merged[norm]["type"] = f["type"]
        else:
            merged[norm] = {
                "name": norm,
                "type": f.get("type", "string"),
                "description": f.get("description", ""),
                "example": f.get("example", ""),
            }

    return list(merged.values())


# --- Schema Discovery ---

_DISCOVER_PROMPT = """You are analyzing a document to discover its implicit schema — the fields/data points that appear in it.

Current known schema (may be empty if this is the first document):
{schema}

New document to analyze:
{text}

Instructions:
1. Identify every distinct data field or piece of structured information in this document.
2. For each field, determine: name (snake_case), type (string/number/date/boolean/enum), and a clear description.
3. If a field matches something in the current schema, keep the existing name. Only add NEW fields not already in the schema.
4. Provide an actual example value from this document for each field.
5. Return the COMPLETE updated schema (existing + new fields).

Return a JSON object:
{{
  "fields": [
    {{"name": "invoice_number", "type": "string", "description": "Unique identifier for the invoice", "example": "INV-2024-0451"}},
    {{"name": "total_amount", "type": "number", "description": "Total amount due", "example": "12500.00"}}
  ]
}}

Output ONLY valid JSON. No markdown fences, no commentary."""


_VERIFY_PROMPT = """Given this document, check which of these fields are present. For each field, extract its value if found and provide an exact quote from the document that supports it.

Fields to check:
{fields}

Document:
{text}

For each field:
- If found, set "present": true, provide the extracted "value", and include a "quote" (exact text snippet from the document proving the value exists). Set "grounded": true.
- If the value seems likely but you cannot find an exact supporting quote, set "grounded": false.
- If not found, set "present": false.

Return JSON:
{{
  "found": [
    {{"name": "invoice_number", "value": "INV-2024-0451", "present": true, "quote": "Invoice Number: INV-2024-0451", "grounded": true}},
    {{"name": "total_amount", "value": "12500.00", "present": true, "quote": "Total Due: $12,500.00", "grounded": true}},
    {{"name": "some_field", "value": null, "present": false, "quote": null, "grounded": false}}
  ]
}}

Output ONLY valid JSON."""


def _chunk_for_llm(text: str, model: str, max_chars: int = 6000) -> list[str]:
    """Split a document into LLM-sized chunks with NO information loss.

    Uses the smart chunker from knowledge_graph if the doc exceeds max_chars.
    Every character of the original document is included across the chunks.
    """
    if not text or not text.strip():
        return []

    from lakshana._utils import estimate_context_limit as _estimate_context_limit

    # Use model's context limit, but leave room for prompt + output (~2000 chars)
    ctx_limit = _estimate_context_limit(model)
    effective_limit = min(max_chars, max(ctx_limit - 3000, 3000))

    if len(text) <= effective_limit:
        return [text]

    # Split at paragraph/sentence/word boundaries, no overlap needed for discovery
    chunks = []
    start = 0
    while start < len(text):
        end = start + effective_limit
        if end < len(text):
            # Try paragraph boundary
            para = text.rfind("\n\n", start + effective_limit // 3, end)
            if para > start:
                end = para
            else:
                # Try sentence boundary
                found_sentence = False
                for sep in [". ", ".\n", "! ", "? "]:
                    sent = text.rfind(sep, start + effective_limit // 3, end)
                    if sent > start:
                        end = sent + 1
                        found_sentence = True
                        break
                if not found_sentence:
                    nl = text.rfind("\n", start + effective_limit // 3, end)
                    if nl > start:
                        end = nl
                    else:
                        # Fall back to word boundary (space) to avoid splitting words
                        sp = text.rfind(" ", start + effective_limit // 3, end)
                        if sp > start:
                            end = sp + 1  # include the space in this chunk

        # Guard against zero-progress: ensure we always advance
        if end <= start:
            end = start + effective_limit

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end

    return chunks if chunks else [text]


def discover_schema_for_cluster(
    texts: list[str],
    doc_names: list[str],
    model: str,
    max_samples: int = 8,
    max_verify: int = 10,
    on_progress=None,
) -> dict:
    """Discover implicit schema from a cluster of similar documents.

    Uses iterative discovery (ReDD pattern) + LLM-based frequency verification.
    NO truncation — long documents are chunked and all chunks are processed.
    """
    from lakshana._utils import parse_json_robust as _parse_json_robust

    n = len(texts)
    if n <= max_samples:
        sample_indices = list(range(n))
    else:
        step = n / max_samples
        sample_indices = [int(i * step) for i in range(max_samples)]

    # Phase 1: Iterative schema discovery (with chunking for long docs)
    schema_fields = []

    for si, idx in enumerate(sample_indices):
        doc_text = texts[idx]
        chunks = _chunk_for_llm(doc_text, model)

        if on_progress:
            chunk_note = f" ({len(chunks)} chunks)" if len(chunks) > 1 else ""
            on_progress(f"Discovering from sample {si+1}/{len(sample_indices)}{chunk_note}...")

        # Process all chunks of this document — no data lost
        for ci, chunk in enumerate(chunks):
            schema_json = json.dumps({"fields": schema_fields}, indent=2) if schema_fields else "{}"

            chunk_header = ""
            if len(chunks) > 1:
                chunk_header = f"\n[This is chunk {ci+1}/{len(chunks)} of the document. Continue identifying fields.]\n"

            prompt = _DISCOVER_PROMPT.replace("{schema}", schema_json).replace("{text}", chunk_header + chunk)

            for attempt in range(2):
                try:
                    resp = call_llm(prompt, model=model, max_tokens=2048, temperature=0.0)
                    raw = resp.text.strip()
                    if raw.startswith("```"):
                        lines = raw.split("\n")
                        lines = [line for line in lines if not line.startswith("```")]
                        raw = "\n".join(lines)

                    data = _parse_json_robust(raw)
                    new_fields = data.get("fields", [])

                    valid = []
                    for f in new_fields:
                        if isinstance(f, dict) and f.get("name"):
                            valid.append({
                                "name": _normalize_field_name(str(f["name"])),
                                "type": str(f.get("type", "string")).strip().lower(),
                                "description": str(f.get("description", "")).strip(),
                                "example": str(f.get("example", "")).strip(),
                            })

                    schema_fields = _merge_field_lists(schema_fields, valid)
                    break

                except Exception as e:
                    if attempt == 0:
                        time.sleep(1)
                    else:
                        logger.warning("Schema discovery failed on doc %d chunk %d: %s", idx, ci, e)
                        if on_progress:
                            on_progress(f"Sample {si+1} chunk {ci+1} failed: {e}")

        if on_progress:
            on_progress(f"Sample {si+1}/{len(sample_indices)}: {len(schema_fields)} fields found")

    if not schema_fields:
        return {"fields": []}

    # Phase 2: LLM-based frequency verification
    # Verify against a spread of docs — each doc counted EXACTLY ONCE
    verify_count = min(n, max_verify)
    # Deduplicate indices to ensure each doc is only verified once
    verify_indices = []
    seen_indices = set()
    if verify_count < n:
        verify_step = n / verify_count
        for i in range(verify_count):
            idx = int(i * verify_step)
            if idx not in seen_indices:
                seen_indices.add(idx)
                verify_indices.append(idx)
    else:
        verify_indices = list(range(n))
    actual_verify_count = len(verify_indices)

    if on_progress:
        on_progress(f"Verifying fields across {actual_verify_count} documents...")

    # Track per-doc results: each doc contributes at most 1 count per field
    field_counts = {f["name"]: 0 for f in schema_fields}
    field_grounded_counts = {f["name"]: 0 for f in schema_fields}
    field_examples = {f["name"]: [] for f in schema_fields}
    field_names_json = json.dumps([f["name"] for f in schema_fields])
    # Per-doc presence matrix for coverage calculation
    doc_field_matrix = []  # [{field_name: True/False, ...}, ...]

    def _verify_one_doc(doc_idx):
        """Verify field presence in one document. Chunks long docs, merges results."""
        doc_text = texts[doc_idx]
        chunks = _chunk_for_llm(doc_text, model, max_chars=4000)

        # Track which fields were found across ALL chunks of this doc
        doc_field_present = {}  # field_name → {present, value, quote, grounded}

        for ci, chunk in enumerate(chunks):
            chunk_header = ""
            if len(chunks) > 1:
                chunk_header = f"[Chunk {ci+1}/{len(chunks)} of document]\n"

            prompt = _VERIFY_PROMPT.replace("{fields}", field_names_json).replace("{text}", chunk_header + chunk)
            try:
                resp = call_llm(prompt, model=model, max_tokens=1024, temperature=0.0)
                raw = resp.text.strip()
                if raw.startswith("```"):
                    lines = raw.split("\n")
                    lines = [line for line in lines if not line.startswith("```")]
                    raw = "\n".join(lines)
                data = _parse_json_robust(raw)

                for ff in data.get("found", []):
                    if isinstance(ff, dict) and ff.get("name"):
                        fname = _normalize_field_name(ff["name"])
                        if ff.get("present", False):
                            # Mark as present (once per doc, not per chunk)
                            if fname not in doc_field_present:
                                doc_field_present[fname] = {
                                    "present": True,
                                    "value": ff.get("value"),
                                    "quote": ff.get("quote"),
                                    "grounded": bool(ff.get("grounded", False)),
                                }
                            else:
                                if ff.get("value") and not doc_field_present[fname].get("value"):
                                    doc_field_present[fname]["value"] = ff.get("value")
                                # Upgrade grounded status if this chunk has a quote
                                if ff.get("grounded") and ff.get("quote"):
                                    doc_field_present[fname]["grounded"] = True
                                    doc_field_present[fname]["quote"] = ff.get("quote")

            except Exception as e:
                logger.warning("Verification failed for doc %d chunk %d: %s", doc_idx, ci, e)

        return doc_idx, doc_field_present

    # Parallel verification (up to 3 concurrent)
    with ThreadPoolExecutor(max_workers=min(3, max(actual_verify_count, 1))) as executor:
        futures = {executor.submit(_verify_one_doc, idx): idx for idx in verify_indices}
        for future in as_completed(futures):
            try:
                doc_idx, doc_fields = future.result()
                doc_presence = {}
                for fname, info in doc_fields.items():
                    if fname in field_counts and info.get("present"):
                        field_counts[fname] += 1
                        # Track grounding
                        if info.get("grounded"):
                            field_grounded_counts[fname] += 1
                        doc_presence[fname] = {
                            "present": True,
                            "grounded": bool(info.get("grounded", False)),
                        }
                        if info.get("quote"):
                            doc_presence[fname]["quote"] = str(info["quote"])[:200]
                        val = info.get("value")
                        if val and len(field_examples.get(fname, [])) < 5:
                            field_examples[fname].append(str(val))
                    elif fname in field_counts:
                        doc_presence[fname] = False
                doc_field_matrix.append(doc_presence)
            except Exception:
                logger.warning("Verification future failed for doc", exc_info=True)

    # Update fields with verified frequency (capped at 100%)
    for f in schema_fields:
        count = field_counts.get(f["name"], 0)
        freq = count / max(actual_verify_count, 1) * 100
        f["frequency"] = round(min(freq, 100.0), 1)  # Never exceed 100%
        f["required"] = f["frequency"] >= 80
        f["doc_count"] = count
        f["grounded_count"] = field_grounded_counts.get(f["name"], 0)
        f["verified_against"] = actual_verify_count
        examples = field_examples.get(f["name"], [])
        if examples:
            f["example"] = examples[0]
            if len(examples) > 1:
                f["examples"] = examples[:5]

    schema_fields.sort(key=lambda f: f.get("frequency", 0), reverse=True)

    # Compute coverage: what % of all field-document cells are filled
    # Coverage = (fields present across all docs) / (total possible field-doc pairs)
    total_cells = len(schema_fields) * actual_verify_count
    filled_cells = sum(field_counts.get(f["name"], 0) for f in schema_fields)
    coverage = round(filled_cells / max(total_cells, 1) * 100, 1)

    # Also store per-doc presence matrix so frontend can recompute when user toggles fields
    return {
        "fields": schema_fields,
        "coverage": coverage,
        "verified_docs": actual_verify_count,
        "doc_field_matrix": doc_field_matrix,
    }


# --- Semantic Field Deduplication ---

_DEDUP_PROMPT = """Given these discovered document fields, identify groups of fields that refer to the same concept (synonyms/duplicates).

Fields:
{fields}

For each group of synonymous fields, choose the best canonical name and list the aliases.
Return JSON:
{{
  "groups": [
    {{"canonical": "customer_name", "aliases": ["client_name", "buyer_name"], "reason": "All refer to the purchasing entity"}},
    {{"canonical": "total_amount", "aliases": ["total", "grand_total"], "reason": "All refer to the final sum"}}
  ]
}}

Only include fields that actually have duplicates. If no duplicates are found, return {{"groups": []}}.
Output ONLY valid JSON."""


def deduplicate_fields(fields: list[dict], model: str) -> list[dict]:
    """Merge semantically duplicate fields using LLM analysis.

    After discovery, sends the field list to the LLM to identify synonymous fields.
    Merges duplicates: keeps the best name, combines examples, adds aliases.
    """
    if not fields or len(fields) < 2:
        return fields

    from lakshana._utils import parse_json_robust as _parse_json_robust

    field_summary = json.dumps(
        [{"name": f["name"], "type": f.get("type", "string"), "description": f.get("description", "")}
         for f in fields],
        indent=2,
    )

    prompt = _DEDUP_PROMPT.replace("{fields}", field_summary)

    try:
        resp = call_llm(prompt, model=model, max_tokens=1024, temperature=0.0)
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            raw = "\n".join(lines)
        data = _parse_json_robust(raw)
    except ValueError as e:
        # Configuration errors (missing API key, unknown provider) should
        # surface to the caller — they're a misconfiguration, not transient.
        if "No API key" in str(e) or "Unknown provider" in str(e) or "Unknown model" in str(e):
            raise
        logger.warning("Field deduplication failed: %s", e)
        return fields
    except Exception as e:
        logger.warning("Field deduplication failed: %s", e)
        return fields

    dedup_groups = data.get("groups", [])
    if not dedup_groups:
        return fields

    # Build a map: alias_normalized -> canonical_normalized
    alias_to_canonical = {}
    canonical_aliases = {}  # canonical_normalized -> list of alias names
    canonical_reasons = {}  # canonical_normalized -> reason
    for group in dedup_groups:
        if not isinstance(group, dict):
            continue
        canonical = _normalize_field_name(str(group.get("canonical", "")))
        aliases = group.get("aliases", [])
        reason = group.get("reason", "")
        if not canonical or not aliases:
            continue
        canonical_aliases[canonical] = [str(a) for a in aliases]
        canonical_reasons[canonical] = reason
        for alias in aliases:
            norm_alias = _normalize_field_name(str(alias))
            if norm_alias and norm_alias != canonical:
                alias_to_canonical[norm_alias] = canonical

    # Merge fields
    merged = {}
    for f in fields:
        norm = _normalize_field_name(f.get("name", ""))
        if not norm:
            continue

        canonical = alias_to_canonical.get(norm, norm)

        if canonical in merged:
            # Merge into existing canonical field
            existing = merged[canonical]
            # Combine examples
            if f.get("example") and f["example"] != existing.get("example", ""):
                ex_list = existing.get("examples", [])
                if existing.get("example") and existing["example"] not in ex_list:
                    ex_list = [existing["example"]] + ex_list
                ex_list.append(f["example"])
                existing["examples"] = list(dict.fromkeys(ex_list))[:5]
            # Prefer longer description
            if len(f.get("description", "")) > len(existing.get("description", "")):
                existing["description"] = f["description"]
            # Prefer more specific type
            if f.get("type") and f["type"] != "string" and existing.get("type") == "string":
                existing["type"] = f["type"]
            # Track higher frequency
            if f.get("frequency", 0) > existing.get("frequency", 0):
                existing["frequency"] = f["frequency"]
                existing["doc_count"] = f.get("doc_count", existing.get("doc_count", 0))
        else:
            merged[canonical] = f.copy()
            merged[canonical]["name"] = canonical

    # Add aliases metadata to canonical fields
    for norm, fld in merged.items():
        if norm in canonical_aliases:
            raw_aliases = canonical_aliases[norm]
            # Only include aliases that were actually different fields
            valid_aliases = [a for a in raw_aliases if _normalize_field_name(a) != norm]
            if valid_aliases:
                fld["aliases"] = valid_aliases

    return list(merged.values())


# --- Smart Merge Suggestions ---

def suggest_merges(fields: list[dict]) -> list[dict]:
    """Suggest field merges based on Levenshtein distance and semantic similarity.

    Uses normalized name comparison (Levenshtein distance < 3) AND description overlap.
    Returns a list of merge suggestions.
    """
    if not fields or len(fields) < 2:
        return []

    suggestions = []
    seen_pairs = set()

    for i, f1 in enumerate(fields):
        for j, f2 in enumerate(fields):
            if j <= i:
                continue
            name1 = _normalize_field_name(f1.get("name", ""))
            name2 = _normalize_field_name(f2.get("name", ""))
            if not name1 or not name2 or name1 == name2:
                continue

            pair_key = tuple(sorted([name1, name2]))
            if pair_key in seen_pairs:
                continue

            # Levenshtein distance on normalized names
            lev_dist = _levenshtein(name1, name2)

            # Semantic similarity: word overlap in descriptions
            desc1_words = set(f1.get("description", "").lower().split())
            desc2_words = set(f2.get("description", "").lower().split())
            desc_overlap = len(desc1_words & desc2_words) / max(len(desc1_words | desc2_words), 1) if desc1_words and desc2_words else 0

            # Check if names share a common root (one contains the other)
            name_contains = name1 in name2 or name2 in name1

            if lev_dist < 3 or (desc_overlap > 0.5 and lev_dist < 6) or name_contains:
                # Pick the better name: prefer the longer, more descriptive name
                suggested = name1 if len(name1) >= len(name2) else name2
                reason_parts = []
                if lev_dist < 3:
                    reason_parts.append(f"similar names (distance={lev_dist})")
                if desc_overlap > 0.5:
                    reason_parts.append(f"similar descriptions ({desc_overlap:.0%} overlap)")
                if name_contains:
                    reason_parts.append("one name contains the other")

                suggestions.append({
                    "fields": [name1, name2],
                    "suggested_name": suggested,
                    "reason": ", ".join(reason_parts),
                })
                seen_pairs.add(pair_key)

    return suggestions


def _levenshtein(s1: str, s2: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row

    return prev_row[-1]


# --- AI-Suggested Field Groups ---

GROUP_COLORS = ['#3868b8', '#5cb85c', '#e74c3c', '#9b59b6', '#f0ad4e', '#1abc9c', '#e67e22']

_GROUP_PROMPT = """Given these discovered document fields, group them into 3-7 semantic categories.

Fields:
{fields}

Return a JSON object with a "groups" array. Each group has a name, description, and list of field names that belong to it.
Important: every field must appear in exactly one group. If a field doesn't fit any category, put it in an "Ungrouped" category.

{{
  "groups": [
    {{"name": "Vendor Information", "description": "Sender/vendor details", "fields": ["vendor_name", "vendor_address"]}},
    {{"name": "Invoice Details", "description": "Core invoice metadata", "fields": ["invoice_number", "invoice_date"]}},
    {{"name": "Line Items", "description": "Repeating line-item rows", "fields": ["item_description", "quantity", "unit_price"], "is_repeating": true}}
  ]
}}

Output ONLY valid JSON."""


def group_fields(fields: list[dict], model: str, doc_type: str = "") -> tuple[list[dict], list[dict]]:
    """Group discovered fields into semantic categories using LLM.

    Uses hybrid embedding + LLM approach when sentence-transformers is available.
    Falls back to LLM-only approach otherwise.

    Returns (updated_fields_with_group_property, groups_list).
    Fields gain an optional `group` property. Groups have name, description, color.
    """
    if not fields:
        return fields, []

    # Try the advanced hybrid approach when doc_type context is available
    try:
        if not doc_type:
            raise ValueError("No doc_type for advanced grouping, use legacy")
        advanced_groups = _group_fields_advanced(fields, doc_type=doc_type, model=model)
        if advanced_groups:
            # Convert advanced format to legacy format
            groups = []
            for gi, ag in enumerate(advanced_groups):
                if not isinstance(ag, dict):
                    continue
                gname = ag.get("name", f"Group {gi + 1}")
                color = GROUP_COLORS[gi % len(GROUP_COLORS)]
                groups.append({
                    "name": gname,
                    "description": ag.get("description", ""),
                    "color": color,
                })
                for f in ag.get("fields", []):
                    if isinstance(f, dict):
                        f["group"] = gname
                    else:
                        # f is a field name string — find and update in fields list
                        norm = _normalize_field_name(str(f))
                        for field in fields:
                            if _normalize_field_name(field.get("name", "")) == norm:
                                field["group"] = gname
            # Assign "Ungrouped" to any missed fields
            for f in fields:
                if "group" not in f:
                    f["group"] = "Ungrouped"
            if any(f.get("group") == "Ungrouped" for f in fields):
                groups.append({"name": "Ungrouped", "description": "Fields not yet categorized", "color": "#9a8e80"})
            return fields, groups
    except Exception as e:
        logger.info("Advanced grouping failed (%s), using legacy approach", e)

    from lakshana._utils import parse_json_robust as _parse_json_robust

    field_summary = json.dumps(
        [{"name": f["name"], "type": f.get("type", "string"), "description": f.get("description", "")}
         for f in fields],
        indent=2,
    )

    prompt = _GROUP_PROMPT.replace("{fields}", field_summary)

    try:
        resp = call_llm(prompt, model=model, max_tokens=1024, temperature=0.0)
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            raw = "\n".join(lines)
        data = _parse_json_robust(raw)
    except Exception as e:
        logger.warning("Field grouping failed: %s", e)
        return fields, []

    # LLMs sometimes return a bare list of groups instead of {"groups": [...]}
    if isinstance(data, list):
        raw_groups = data
    elif isinstance(data, dict):
        raw_groups = data.get("groups", [])
    else:
        raw_groups = []
    if not raw_groups:
        return fields, []

    # Build the groups list with colors
    groups = []
    field_to_group = {}  # field_name -> group_name

    for gi, g in enumerate(raw_groups):
        if not isinstance(g, dict):
            continue
        gname = str(g.get("name", f"Group {gi + 1}")).strip()
        gdesc = str(g.get("description", "")).strip()
        color = GROUP_COLORS[gi % len(GROUP_COLORS)]
        is_repeating = bool(g.get("is_repeating", False))

        group_entry = {"name": gname, "description": gdesc, "color": color}
        if is_repeating:
            group_entry["is_repeating"] = True
        groups.append(group_entry)

        for fname in g.get("fields", []):
            norm = _normalize_field_name(str(fname))
            if norm:
                field_to_group[norm] = gname

    # Assign group property to fields
    ungrouped_fields = []
    for f in fields:
        norm = _normalize_field_name(f.get("name", ""))
        if norm in field_to_group:
            f["group"] = field_to_group[norm]
        else:
            ungrouped_fields.append(f)
            f["group"] = "Ungrouped"

    # Add "Ungrouped" group if there are ungrouped fields
    if ungrouped_fields:
        groups.append({
            "name": "Ungrouped",
            "description": "Fields not yet categorized",
            "color": "#9a8e80",
        })

    return fields, groups


# --- Cluster Labeling ---

_LABEL_PROMPT = """I have a cluster of similar documents. Here are representative excerpts:

{excerpts}

Based on these documents:
1. Give this document type a short name (2-4 words, e.g., "Invoice", "Damage Report", "Meeting Minutes")
2. Write a one-sentence description of what these documents contain
3. List 3-5 distinguishing keywords

Return JSON:
{{
  "name": "Invoice",
  "description": "Standard commercial invoices with line items, totals, and payment terms",
  "keywords": ["invoice", "total", "payment", "due date", "line items"]
}}

Output ONLY valid JSON."""


def label_cluster(texts: list[str], model: str) -> dict:
    """Generate a human-readable label for a document cluster."""
    from lakshana._utils import parse_json_robust as _parse_json_robust

    excerpts = []
    for i, t in enumerate(texts[:5]):
        excerpts.append(f"--- Document {i+1} ---\n{t[:600]}")
    excerpts_text = "\n\n".join(excerpts)

    prompt = _LABEL_PROMPT.replace("{excerpts}", excerpts_text)

    for attempt in range(2):
        try:
            resp = call_llm(prompt, model=model, max_tokens=512, temperature=0.0)
            raw = resp.text.strip()
            if raw.startswith("```"):
                lines = raw.split("\n")
                lines = [line for line in lines if not line.startswith("```")]
                raw = "\n".join(lines)
            return _parse_json_robust(raw)
        except Exception as e:
            if attempt == 0:
                time.sleep(1)
            else:
                logger.warning("Cluster labeling failed: %s", e)
                return {"name": "Unknown Type", "description": "Could not determine document type", "keywords": []}
    return {"name": "Unknown Type", "description": "", "keywords": []}


# --- Field Grouping (hybrid embedding + LLM) ---

# Reference sections per document type for ontology-anchored naming
REFERENCE_SECTIONS = {
    "invoice": [
        "Vendor Details", "Buyer Details", "Invoice Metadata",
        "Line Items", "Payment Terms", "Tax & Totals",
    ],
    "contract": [
        "Parties", "Agreement Terms", "Scope of Work",
        "Compensation", "Dates & Deadlines", "Signatures",
    ],
    "resume": [
        "Contact Information", "Professional Summary", "Work Experience",
        "Education", "Skills & Certifications", "References",
    ],
    "report": [
        "Report Header", "Executive Summary", "Findings",
        "Data & Metrics", "Recommendations", "Appendix",
    ],
    "receipt": [
        "Store Information", "Transaction Details", "Items Purchased",
        "Taxes & Fees", "Payment Summary",
    ],
    "purchase_order": [
        "Buyer Details", "Supplier Details", "Order Metadata",
        "Line Items", "Shipping & Delivery", "Terms & Totals",
    ],
}

# Names that are too generic to be useful -- will be rejected
_BANNED_GROUP_NAMES = {
    "general information", "other details", "miscellaneous",
    "additional information", "other", "general", "misc",
    "various", "unclassified", "uncategorized",
    "additional details", "extra information", "other fields",
    "remaining fields", "more details", "supplementary",
}

_GROUP_PROMPT = """You are naming groups of related document fields.
These fields come from a "{doc_type}" document type.

I have pre-clustered these fields into groups by semantic similarity.
Your job is ONLY to assign a clear, specific name to each group.

Reference section names for this document type:
{reference_sections}

Pre-formed groups to name:
{groups}

Rules:
1. Use 2-4 word names that are specific to the document domain
2. NEVER use generic names like "General Information", "Other Details", "Miscellaneous", etc.
3. If a group doesn't clearly map to a reference section, invent a specific name based on the actual fields
4. Each name must be unique

Return a JSON array of objects:
[
  {{"group_index": 0, "name": "Vendor Details", "rationale": "Contains vendor_name, vendor_address, vendor_id"}},
  {{"group_index": 1, "name": "Line Items", "rationale": "Contains item descriptions and prices"}}
]

Output ONLY valid JSON. No markdown fences."""


def _group_fields_advanced(
    fields: list[dict],
    doc_type: str = "",
    model: str = "groq/llama-3.3-70b-versatile",
    n_groups: int | None = None,
) -> list[dict]:
    """Group schema fields into named sections using hybrid embedding + LLM.

    Strategy:
    1. Embed field names+descriptions using sentence-transformers
    2. Cluster embeddings with AgglomerativeClustering (pre-grouping)
    3. Ask LLM only to NAME the pre-formed clusters (not group AND name)

    Falls back to LLM-only approach if sentence-transformers is not installed.

    Args:
        fields: List of field dicts with at least "name" key
        doc_type: Document type name for context-specific naming
        model: LLM model for naming
        n_groups: Target number of groups (auto-detected if None)

    Returns:
        List of group dicts: [{"name": "...", "fields": [...]}]
    """
    if not fields:
        return []

    if len(fields) <= 3:
        # Too few fields to group meaningfully
        return [{"name": _infer_single_group_name(fields, doc_type), "fields": fields}]

    # Try hybrid approach (embedding + LLM naming)
    try:
        return _group_fields_hybrid(fields, doc_type, model, n_groups)
    except ImportError:
        logger.info("sentence-transformers not available, falling back to LLM-only grouping")
        return _group_fields_llm_only(fields, doc_type, model, n_groups)
    except Exception as e:
        logger.warning("Hybrid grouping failed: %s, falling back to LLM-only", e)
        return _group_fields_llm_only(fields, doc_type, model, n_groups)


def _group_fields_hybrid(
    fields: list[dict],
    doc_type: str,
    model: str,
    n_groups: int | None,
) -> list[dict]:
    """Group fields using embedding-based pre-clustering + LLM naming."""
    from sentence_transformers import SentenceTransformer
    from sklearn.cluster import AgglomerativeClustering

    # Build text representations for embedding
    texts = []
    for f in fields:
        name = f.get("name", "").replace("_", " ")
        desc = f.get("description", "")
        example = f.get("example", "")
        text = f"{name}: {desc}" if desc else name
        if example:
            text += f" (e.g., {example})"
        texts.append(text)

    # Embed
    st_model = SentenceTransformer("all-MiniLM-L6-v2")
    embeddings = st_model.encode(texts, normalize_embeddings=True)

    # Determine number of clusters
    if n_groups is None:
        n_groups = max(2, min(len(fields) // 4, 8))

    n_groups = min(n_groups, len(fields))

    # Cluster
    clustering = AgglomerativeClustering(
        n_clusters=n_groups,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(embeddings)

    # Form pre-groups
    pre_groups = {}
    for i, label in enumerate(labels):
        label = int(label)
        if label not in pre_groups:
            pre_groups[label] = []
        pre_groups[label].append(fields[i])

    # Ask LLM to name the pre-formed groups
    group_descriptions = []
    for idx in sorted(pre_groups.keys()):
        group_fields_list = pre_groups[idx]
        field_names = [f.get("name", "") for f in group_fields_list]
        group_descriptions.append(f"Group {idx}: {', '.join(field_names)}")

    groups_text = "\n".join(group_descriptions)

    # Get reference sections
    doc_type_lower = doc_type.lower().strip()
    ref_sections = REFERENCE_SECTIONS.get(doc_type_lower, [])
    if not ref_sections:
        # Try partial matching
        for key, sections in REFERENCE_SECTIONS.items():
            if key in doc_type_lower or doc_type_lower in key:
                ref_sections = sections
                break
    ref_text = ", ".join(ref_sections) if ref_sections else "No specific references available -- use domain-appropriate names"

    prompt = _GROUP_PROMPT.format(
        doc_type=doc_type or "document",
        reference_sections=ref_text,
        groups=groups_text,
    )

    try:
        from lakshana._utils import parse_json_robust as _parse_json_robust

        resp = call_llm(prompt, model=model, max_tokens=1024, temperature=0.0)
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            raw = "\n".join(lines)

        naming_result = _parse_json_robust(raw)

        # Build final groups
        name_map = {}
        if isinstance(naming_result, list):
            for item in naming_result:
                if isinstance(item, dict):
                    idx = item.get("group_index", -1)
                    name = item.get("name", "")
                    name_map[idx] = name

        result = []
        for idx in sorted(pre_groups.keys()):
            name = name_map.get(idx, f"Section {idx + 1}")
            name = _validate_group_name(name, idx, doc_type)
            result.append({
                "name": name,
                "fields": pre_groups[idx],
            })

        return result

    except Exception as e:
        logger.warning("LLM naming failed: %s, using fallback names", e)
        result = []
        for idx in sorted(pre_groups.keys()):
            result.append({
                "name": f"Section {idx + 1}",
                "fields": pre_groups[idx],
            })
        return result


def _group_fields_llm_only(
    fields: list[dict],
    doc_type: str,
    model: str,
    n_groups: int | None,
) -> list[dict]:
    """Fallback: LLM-only field grouping (when sentence-transformers unavailable)."""
    from lakshana._utils import parse_json_robust as _parse_json_robust

    field_list = json.dumps([
        {"name": f.get("name", ""), "type": f.get("type", "string"),
         "description": f.get("description", "")}
        for f in fields
    ], indent=2)

    doc_type_lower = doc_type.lower().strip()
    ref_sections = REFERENCE_SECTIONS.get(doc_type_lower, [])
    ref_text = ", ".join(ref_sections) if ref_sections else "Use domain-appropriate section names"

    target = n_groups or max(2, min(len(fields) // 4, 8))

    prompt = f"""Group these fields from a "{doc_type or 'document'}" into {target} logical sections.

Reference section names: {ref_text}

Fields:
{field_list}

Rules:
1. Group related fields together
2. Use 2-4 word names specific to the document domain
3. NEVER use generic names like "General Information", "Other Details", "Miscellaneous"
4. Each field must appear in exactly one group

Return JSON array:
[
  {{"name": "Vendor Details", "field_names": ["vendor_name", "vendor_address"]}},
  {{"name": "Line Items", "field_names": ["item_description", "item_price"]}}
]

Output ONLY valid JSON."""

    try:
        resp = call_llm(prompt, model=model, max_tokens=1024, temperature=0.0)
        raw = resp.text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            lines = [line for line in lines if not line.startswith("```")]
            raw = "\n".join(lines)

        grouping = _parse_json_robust(raw)

        if not isinstance(grouping, list):
            raise ValueError("Expected a JSON array")

        # Build field lookup
        field_by_name = {f.get("name", ""): f for f in fields}
        assigned = set()
        result = []

        for i, g in enumerate(grouping):
            if not isinstance(g, dict):
                continue
            name = g.get("name", f"Section {i + 1}")
            name = _validate_group_name(name, i, doc_type)
            field_names = g.get("field_names", [])

            group_fields_list = []
            for fn in field_names:
                if fn in field_by_name and fn not in assigned:
                    group_fields_list.append(field_by_name[fn])
                    assigned.add(fn)

            if group_fields_list:
                result.append({"name": name, "fields": group_fields_list})

        # Add unassigned fields
        unassigned = [f for f in fields if f.get("name", "") not in assigned]
        if unassigned:
            result.append({"name": "Document Properties", "fields": unassigned})

        return result

    except Exception as e:
        logger.warning("LLM-only grouping failed: %s", e)
        return [{"name": _infer_single_group_name(fields, doc_type), "fields": fields}]


def _validate_group_name(name: str, index: int, doc_type: str) -> str:
    """Validate a group name, rejecting generic names."""
    if not name or name.lower().strip() in _BANNED_GROUP_NAMES:
        # Generate a fallback based on doc type
        doc_type_lower = doc_type.lower().strip()
        ref_sections = REFERENCE_SECTIONS.get(doc_type_lower, [])
        if ref_sections and index < len(ref_sections):
            return ref_sections[index]
        return f"{doc_type or 'Document'} Section {index + 1}"
    return name.strip()


def _infer_single_group_name(fields: list[dict], doc_type: str) -> str:
    """Infer a name for a single group of fields."""
    if doc_type:
        return f"{doc_type} Fields"
    return "Document Fields"


# --- Main Pipeline ---

def run_discovery(
    files: list[str],
    model: str = "groq/llama-3.3-70b-versatile",
    min_cluster_size: int = 3,
    on_progress=None,
) -> DiscoverResult:
    """Run the full template discovery pipeline.

    Args:
        files: list of file paths to discover schemas from.
        model: LLM model id, e.g. ``"groq/llama-3.3-70b-versatile"``.
        min_cluster_size: minimum docs that form a discovered cluster.
        on_progress: optional callback ``(stage, message, pct)``.

    Raises:
        TypeError: if ``files`` is not a list/tuple of strings.
        ValueError: if ``files`` is empty or ``min_cluster_size < 2``.
        FileNotFoundError: if any file in ``files`` doesn't exist on disk.

    Returns:
        DiscoverResult. Even on a partial / no-cluster run, ``result.stats``
        will be populated with diagnostic fields so the caller can tell
        what happened without parsing logs.
    """
    # --- Input validation (fail fast, with actionable messages) -----------
    if not isinstance(files, (list, tuple)):
        raise TypeError(
            f"`files` must be a list of paths, got {type(files).__name__}. "
            f"Use lakshana.discover_from_strings(texts) if you have raw text."
        )
    if not files:
        raise ValueError(
            "`files` is empty — pass at least one document path. "
            "Use lakshana.discover_from_strings(texts) for raw strings."
        )
    bad_types = [(i, type(f).__name__) for i, f in enumerate(files) if not isinstance(f, (str, Path))]
    if bad_types:
        raise TypeError(
            f"All entries in `files` must be str or pathlib.Path; "
            f"got non-path entries at positions {bad_types[:3]}{'...' if len(bad_types) > 3 else ''}."
        )
    files = [str(f) for f in files]
    missing = [f for f in files if not Path(f).exists()]
    if missing:
        sample = missing[:3]
        raise FileNotFoundError(
            f"{len(missing)} of {len(files)} file(s) do not exist on disk. "
            f"First missing: {sample}{'...' if len(missing) > 3 else ''}"
        )
    if not isinstance(min_cluster_size, int) or min_cluster_size < 2:
        raise ValueError(
            f"min_cluster_size must be an int >= 2; got {min_cluster_size!r}."
        )

    # Soft warning if min_cluster_size > n_files — we don't lower it
    # silently because that may surprise the caller; we surface it.
    n_input = len(files)
    if min_cluster_size > n_input:
        logger.warning(
            "min_cluster_size=%d exceeds number of input files (%d). "
            "HDBSCAN will likely produce 0 clusters; result.stats['warning'] will reflect this.",
            min_cluster_size, n_input,
        )

    result = DiscoverResult()
    # Always-populated diagnostic fields, even on early exit
    result.stats = {
        "n_input_files": n_input,
        "model": model,
        "min_cluster_size": min_cluster_size,
        "total_docs": 0,
        "parsed_errors": 0,
        "clusters": 0,
        "total_fields": 0,
        "duration_s": 0.0,
    }
    start_time = time.time()

    def _progress(stage, msg, pct=0):
        result.logs.append(msg)
        if on_progress:
            try:
                on_progress(stage, msg, pct)
            except Exception:
                logger.debug("Progress callback failed for stage=%s", stage)

    # Step 1: Parse all documents (parallel for speed)
    _progress("parse", f"Extracting text from {len(files)} documents...", 5)
    texts = []
    doc_names = []
    parse_errors = 0

    def _parse_one(fp):
        try:
            t = extract_text_from_file(fp)
            return Path(fp).name, t if t.strip() else None
        except Exception:
            return Path(fp).name, None

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(_parse_one, fp): fp for fp in files}
        for future in as_completed(futures):
            name, text = future.result()
            if text:
                texts.append(text)
                doc_names.append(name)
            else:
                parse_errors += 1

    _progress("parse", f"Parsed {len(texts)} documents ({parse_errors} failed/empty)", 20)
    result.stats["parsed_errors"] = parse_errors
    result.stats["total_docs"] = len(texts)

    if len(texts) < 2:
        warning = (
            f"Only {len(texts)} document(s) yielded extractable text "
            f"(out of {n_input}, with {parse_errors} parse failures or empty results). "
            f"Discovery requires at least 2 documents."
        )
        result.stats["warning"] = warning
        result.stats["duration_s"] = round(time.time() - start_time, 1)
        _progress("error", warning, 0)
        return result

    if len(texts) < min_cluster_size:
        warning = (
            f"Only {len(texts)} document(s) parsed successfully, but "
            f"min_cluster_size={min_cluster_size}. HDBSCAN will not form any "
            f"cluster. Lower min_cluster_size or add more documents."
        )
        result.stats["warning"] = warning

    result.doc_names = doc_names
    result.doc_snippets = [t[:500] for t in texts]

    # Step 2: Generate embeddings
    _progress("embed", f"Generating embeddings for {len(texts)} documents...", 25)
    try:
        embeddings = embed_documents(texts, doc_names)
        result.embeddings = embeddings
        _progress("embed", f"Embeddings: {embeddings.shape[0]} docs × {embeddings.shape[1]} dims", 35)
    except Exception as e:
        _progress("error", f"Embedding failed: {e}", 0)
        return result

    # Step 3: Cluster documents
    _progress("cluster", "Clustering with UMAP + HDBSCAN...", 40)
    try:
        labels, umap_2d, umap_3d = cluster_documents(embeddings, min_cluster_size=min_cluster_size)
        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        if n_clusters == 0:
            n_clusters = 1
            labels = np.zeros(len(texts), dtype=int)
        _progress("cluster", f"Found {n_clusters} cluster(s)", 50)
        result.umap_coords = umap_2d.tolist()
        result.umap_3d = umap_3d.tolist()
        result.doc_cluster_ids = labels.tolist()
    except Exception as e:
        _progress("error", f"Clustering failed: {e}", 0)
        labels = np.zeros(len(texts), dtype=int)
        result.umap_coords = [[float(i), 0.0] for i in range(len(texts))]
        result.umap_3d = [[float(i), 0.0, 0.0] for i in range(len(texts))]
        result.doc_cluster_ids = labels.tolist()
        n_clusters = 1

    # Step 4: Label and discover schema per cluster
    unique_clusters = sorted(set(labels))
    if -1 in unique_clusters:
        unique_clusters.remove(-1)
    if not unique_clusters:
        unique_clusters = [0]

    clusters_info = []
    schemas = {}

    for ci, cluster_id in enumerate(unique_clusters):
        cluster_id = int(cluster_id)
        pct = 50 + int(((ci + 1) / len(unique_clusters)) * 40)

        indices = [i for i, label in enumerate(labels) if label == cluster_id]
        cluster_texts = [texts[i] for i in indices]
        cluster_names = [doc_names[i] for i in indices]

        _progress("discover", f"Cluster {ci+1}/{len(unique_clusters)}: {len(indices)} docs — labeling...", pct)

        label_info = label_cluster(cluster_texts, model)

        _progress("discover", f"Cluster '{label_info.get('name', '?')}': discovering schema...", pct)

        def _schema_progress(msg):
            _progress("discover", f"  {msg}", pct)

        schema = discover_schema_for_cluster(
            cluster_texts, cluster_names, model,
            on_progress=_schema_progress,
        )

        # Post-discovery: deduplicate, group, and suggest merges
        if schema.get("fields"):
            # Step 4a: Deduplicate semantically similar fields
            _progress("discover", "  Deduplicating fields...", pct)
            try:
                schema["fields"] = deduplicate_fields(schema["fields"], model)
                _progress("discover", f"  After dedup: {len(schema['fields'])} fields", pct)
            except Exception as e:
                logger.warning("Deduplication failed for cluster %d: %s", cluster_id, e)

            # Step 4b: Group fields into semantic categories
            _progress("discover", "  Grouping fields...", pct)
            try:
                schema["fields"], groups = group_fields(schema["fields"], model, doc_type=label_info.get("name", ""))
                if groups:
                    schema["groups"] = groups
                    _progress("discover", f"  Grouped into {len(groups)} categories", pct)
            except Exception as e:
                logger.warning("Grouping failed for cluster %d: %s", cluster_id, e)

            # Step 4c: Suggest potential merges
            try:
                merge_suggestions = suggest_merges(schema["fields"])
                if merge_suggestions:
                    schema["merge_suggestions"] = merge_suggestions
                    _progress("discover", f"  {len(merge_suggestions)} merge suggestion(s)", pct)
            except Exception as e:
                logger.warning("Merge suggestions failed for cluster %d: %s", cluster_id, e)

        clusters_info.append({
            "id": cluster_id,
            "name": label_info.get("name", f"Type {cluster_id + 1}"),
            "description": label_info.get("description", ""),
            "keywords": label_info.get("keywords", []),
            "doc_count": len(indices),
            "doc_indices": indices,
        })

        schemas[str(cluster_id)] = schema
        _progress("discover", f"  Schema: {len(schema.get('fields', []))} fields discovered", pct)

    result.clusters = clusters_info
    result.schemas = schemas

    # Step 5: Sub-cluster detection
    _progress("discover", "Detecting sub-clusters...", 92)
    try:
        subclusters = detect_subclusters(embeddings, labels)
        if subclusters:
            for ci in clusters_info:
                cid = ci["id"]
                if cid in subclusters:
                    ci["subclusters"] = subclusters[cid]
            _progress("discover", f"Found sub-clusters in {len(subclusters)} cluster(s)", 94)
    except Exception as e:
        logger.warning("Sub-cluster detection failed: %s", e)

    # Step 6: Cross-cluster field linking
    _progress("discover", "Linking cross-cluster fields...", 96)
    try:
        cross_fields = find_cross_cluster_fields(schemas)
        if cross_fields:
            result.stats["cross_cluster_fields"] = cross_fields
            _progress("discover", f"Found {len(cross_fields)} field(s) shared across clusters", 98)
    except Exception as e:
        logger.warning("Cross-cluster field linking failed: %s", e)

    result.stats.update({
        "total_docs": len(texts),
        "parsed_errors": parse_errors,
        "clusters": len(clusters_info),
        "total_fields": sum(len(s.get("fields", [])) for s in schemas.values()),
        "duration_s": round(time.time() - start_time, 1),
    })

    _progress("complete", f"Discovery complete: {result.stats['clusters']} clusters, {result.stats['total_fields']} fields in {result.stats['duration_s']}s", 100)
    return result


def discover_from_strings(
    texts: list[str],
    names: list[str] | None = None,
    model: str = "groq/llama-3.3-70b-versatile",
    min_cluster_size: int = 3,
    on_progress=None,
) -> DiscoverResult:
    """Run discovery directly on in-memory strings — no tempfiles needed.

    A convenience wrapper around ``discover()`` for the common case where
    you already have document text in memory (e.g. from a database, web
    scraper, or upstream OCR pass) and don't want to write to disk just
    to feed it in.

    Args:
        texts: list of document texts.
        names: optional matching list of display names. Defaults to
            ``["doc_00.txt", "doc_01.txt", ...]``.
        model, min_cluster_size, on_progress: same as ``discover()``.

    Raises:
        TypeError: if ``texts`` is not a list of strings.
        ValueError: if ``texts`` is empty, or if ``names`` is given but
            doesn't match the length of ``texts``.
    """
    import tempfile

    if not isinstance(texts, (list, tuple)):
        raise TypeError(
            f"`texts` must be a list of strings, got {type(texts).__name__}"
        )
    if not texts:
        raise ValueError("`texts` is empty — pass at least one document string.")
    bad = [(i, type(t).__name__) for i, t in enumerate(texts) if not isinstance(t, str)]
    if bad:
        raise TypeError(
            f"All entries in `texts` must be str; got non-str at positions {bad[:3]}"
            f"{'...' if len(bad) > 3 else ''}"
        )
    if names is not None:
        if len(names) != len(texts):
            raise ValueError(
                f"`names` length ({len(names)}) does not match `texts` length ({len(texts)})"
            )

    tmpdir = Path(tempfile.mkdtemp(prefix="lakshana_strings_"))
    try:
        files = []
        for i, t in enumerate(texts):
            n = names[i] if names else f"doc_{i:02d}.txt"
            # Force .txt suffix so the ingest layer picks the plain-text reader
            if not n.lower().endswith((".txt", ".md", ".log", ".csv", ".tsv", ".json", ".xml", ".html")):
                n = f"{n}.txt"
            p = tmpdir / n
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(t, encoding="utf-8")
            files.append(str(p))
        return run_discovery(
            files=files,
            model=model,
            min_cluster_size=min_cluster_size,
            on_progress=on_progress,
        )
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# --- Export ---

def export_as_json_schema(schema: dict, name: str = "Discovered Template") -> dict:
    """Convert discovered schema to JSON Schema format."""
    properties = {}
    required = []

    for f in schema.get("fields", []):
        type_map = {
            "string": "string", "number": "number", "date": "string",
            "boolean": "boolean", "enum": "string", "integer": "integer",
        }
        prop = {
            "type": type_map.get(f.get("type", "string"), "string"),
            "description": f.get("description", ""),
        }
        if f.get("type") == "date":
            prop["format"] = "date"
        if f.get("example"):
            prop["examples"] = [f["example"]]
        if f.get("examples"):
            prop["examples"] = f["examples"][:5]
        properties[f["name"]] = prop
        if f.get("required"):
            required.append(f["name"])

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": name,
        "type": "object",
        "properties": properties,
        "required": required,
    }


def export_as_structure_entities(schema: dict) -> list[dict]:
    """Convert discovered schema to Structure entity format."""
    entities = []
    for f in schema.get("fields", []):
        type_map = {"number": "float", "integer": "int", "boolean": "string"}
        entities.append({
            "name": f["name"],
            "description": f.get("description", ""),
            "type": type_map.get(f.get("type", "string"), f.get("type", "string")),
            "required": f.get("required", False),
        })
    return entities


def export_as_csv_headers(schema: dict) -> str:
    """Generate CSV with headers + example row."""
    fields = schema.get("fields", [])
    if not fields:
        return "\n"

    def _csv_escape(val: str) -> str:
        """Escape a value for CSV: quote if it contains comma, quote, or newline."""
        val = str(val)
        if ',' in val or '"' in val or '\n' in val:
            return '"' + val.replace('"', '""') + '"'
        return val

    headers = [_csv_escape(f["name"]) for f in fields]
    examples = ['"' + str(f.get("example", "")).replace('"', '""') + '"' for f in fields]
    return ",".join(headers) + "\n" + ",".join(examples) + "\n"


def export_as_markdown(schema: dict, name: str = "Discovered Template") -> str:
    """Generate Markdown documentation for the schema."""
    lines = [f"# {name}", ""]
    fields = schema.get("fields", [])
    if not fields:
        return f"# {name}\n\nNo fields discovered.\n"

    lines.append("| Field | Type | Required | Frequency | Description |")
    lines.append("|-------|------|----------|-----------|-------------|")
    for f in fields:
        req = "Yes" if f.get("required") else "No"
        freq = f"{f.get('frequency', 0)}%"
        lines.append(f"| `{f['name']}` | {f.get('type', 'string')} | {req} | {freq} | {f.get('description', '')} |")

    return "\n".join(lines) + "\n"
