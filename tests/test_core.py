"""Tests for the template discovery module."""

import json
import numpy as np
from unittest.mock import patch, MagicMock

from lakshana.core import (
    structural_fingerprint,
    cluster_documents,
    discover_schema_for_cluster,
    label_cluster,
    run_discovery,
    export_as_json_schema,
    export_as_structure_entities,
    export_as_csv_headers,
    export_as_markdown,
    DiscoverResult,
    _normalize_field_name,
    _merge_field_lists,
    _chunk_for_llm,
    deduplicate_fields,
    suggest_merges,
    group_fields,
    _levenshtein,
    GROUP_COLORS,
    detect_subclusters,
    find_cross_cluster_fields,
)


# --- Structural Fingerprinting ---

def test_structural_fingerprint_basic():
    text = "Invoice Number: INV-2024-001\nDate: 2024-01-15\nTotal: $1,500.00"
    fp = structural_fingerprint(text)
    assert isinstance(fp, list)
    assert len(fp) > 10
    assert all(isinstance(v, float) for v in fp)


def test_structural_fingerprint_dates():
    text = "Date: 2024-01-15\nDue: 2024-02-15\nIssued: January 5, 2024"
    fp = structural_fingerprint(text)
    # Binary flags are at the end — check that at least one date flag is set
    assert any(v == 1.0 for v in fp), "Should detect date patterns"


def test_structural_fingerprint_amounts():
    text = "Total: $15,000.00\nSubtotal: $12,500.00\nTax: $2,500.00"
    fp = structural_fingerprint(text)
    assert any(v == 1.0 for v in fp), "Should detect amount patterns"


def test_structural_fingerprint_empty():
    fp = structural_fingerprint("")
    assert isinstance(fp, list)
    assert len(fp) > 10


def test_structural_fingerprint_kv_pairs():
    text = "Name: John Smith\nAge: 30\nEmail: john@example.com\nPhone: 555-1234"
    fp = structural_fingerprint(text)
    assert fp[17] == 1.0  # has_kv_pairs flag (>3 KV pairs)


# --- Clustering ---

def test_cluster_documents_too_few():
    """With <3 docs, should return single cluster."""
    embeddings = np.random.randn(2, 10).astype("float32")
    labels, coords_2d, coords_3d = cluster_documents(embeddings)
    assert len(labels) == 2
    assert len(coords_2d) == 2
    assert coords_3d.shape[1] == 3
    assert all(label == 0 for label in labels)


def test_cluster_documents_single():
    """Single document — single cluster."""
    embeddings = np.random.randn(1, 10).astype("float32")
    labels, coords_2d, coords_3d = cluster_documents(embeddings)
    assert len(labels) == 1
    assert labels[0] == 0


def test_cluster_documents_small_group():
    """10 docs in 2 clear groups."""
    np.random.seed(42)
    group1 = np.random.randn(5, 50).astype("float32") + 5
    group2 = np.random.randn(5, 50).astype("float32") - 5
    embeddings = np.vstack([group1, group2])
    labels, coords_2d, coords_3d = cluster_documents(embeddings, min_cluster_size=2)
    assert len(labels) == 10
    assert len(coords_2d) == 10
    assert coords_2d.shape == (10, 2)
    assert coords_3d.shape == (10, 3)
    assert len(set(labels)) >= 1


# --- Export ---

def test_export_json_schema():
    schema = {
        "fields": [
            {"name": "invoice_number", "type": "string", "description": "Unique invoice ID", "required": True, "example": "INV-001"},
            {"name": "total", "type": "number", "description": "Total amount", "required": False, "example": "1500.00"},
            {"name": "date", "type": "date", "description": "Invoice date", "required": True, "example": "2024-01-15"},
        ]
    }
    result = export_as_json_schema(schema, "Test Invoice")
    assert result["title"] == "Test Invoice"
    assert "invoice_number" in result["properties"]
    assert result["properties"]["invoice_number"]["type"] == "string"
    assert result["properties"]["total"]["type"] == "number"
    assert result["properties"]["date"]["format"] == "date"
    assert "invoice_number" in result["required"]
    assert "date" in result["required"]
    assert "total" not in result["required"]


def test_export_json_schema_empty():
    result = export_as_json_schema({"fields": []})
    assert result["properties"] == {}
    assert result["required"] == []


def test_export_structure_entities():
    schema = {
        "fields": [
            {"name": "vendor", "type": "string", "description": "Vendor name", "required": True},
            {"name": "amount", "type": "number", "description": "Dollar amount", "required": False},
        ]
    }
    entities = export_as_structure_entities(schema)
    assert len(entities) == 2
    assert entities[0]["name"] == "vendor"
    assert entities[0]["type"] == "string"
    assert entities[0]["required"] is True
    assert entities[1]["name"] == "amount"
    assert entities[1]["type"] == "float"  # number → float


def test_export_csv_headers():
    schema = {
        "fields": [
            {"name": "name", "type": "string", "example": "John"},
            {"name": "age", "type": "number", "example": "30"},
        ]
    }
    csv = export_as_csv_headers(schema)
    lines = csv.strip().split("\n")
    assert lines[0] == "name,age"
    assert '"John"' in lines[1]
    assert '"30"' in lines[1]


def test_export_markdown():
    schema = {
        "fields": [
            {"name": "title", "type": "string", "description": "Document title", "required": True, "frequency": 95},
        ]
    }
    md = export_as_markdown(schema, "Test Doc")
    assert "# Test Doc" in md
    assert "| `title`" in md
    assert "95%" in md
    assert "Yes" in md


def test_export_markdown_empty():
    md = export_as_markdown({"fields": []}, "Empty")
    assert "No fields discovered" in md


# --- Schema Discovery (mocked LLM) ---

@patch("lakshana.core.call_llm")
def test_discover_schema_mocked(mock_llm):
    """Test iterative schema discovery with mocked LLM."""
    mock_llm.return_value = MagicMock(text=json.dumps({
        "fields": [
            {"name": "invoice_number", "type": "string", "description": "Invoice ID", "example": "INV-001"},
            {"name": "total_amount", "type": "number", "description": "Total due", "example": "1500"},
        ]
    }))

    texts = [
        "Invoice Number: INV-001\nTotal: $1,500.00\nDate: 2024-01-15",
        "Invoice Number: INV-002\nTotal: $2,300.00\nDate: 2024-02-20",
        "Invoice Number: INV-003\nTotal: $800.00\nDate: 2024-03-10",
    ]
    result = discover_schema_for_cluster(texts, ["inv1.txt", "inv2.txt", "inv3.txt"], model="test-model", max_samples=2, max_verify=2)

    assert "fields" in result
    assert len(result["fields"]) >= 1
    assert any(f["name"] == "invoice_number" for f in result["fields"])
    # LLM called for: discovery (max_samples=2) + verification (max_verify=2) = ~4 calls
    assert mock_llm.call_count >= 2


@patch("lakshana.core.call_llm")
def test_label_cluster_mocked(mock_llm):
    """Test cluster labeling with mocked LLM."""
    mock_llm.return_value = MagicMock(text=json.dumps({
        "name": "Invoice",
        "description": "Standard commercial invoices",
        "keywords": ["invoice", "total", "payment"]
    }))

    texts = ["Invoice #001 Total: $500", "Invoice #002 Total: $300"]
    result = label_cluster(texts, model="test-model")

    assert result["name"] == "Invoice"
    assert "keywords" in result
    assert len(result["keywords"]) > 0


# --- Full Pipeline (mocked) ---

@patch("lakshana.core.call_llm")
@patch("lakshana.core.extract_text_from_file")
def test_run_discovery_mocked(mock_extract, mock_llm):
    """Test full pipeline with mocked file reading and LLM."""
    # Mock file text extraction
    mock_extract.side_effect = [
        "Invoice Number: INV-001\nTotal: $1,500.00\nVendor: Acme Corp\nDate: 2024-01-15",
        "Invoice Number: INV-002\nTotal: $2,300.00\nVendor: Beta Inc\nDate: 2024-02-20",
        "Invoice Number: INV-003\nTotal: $800.00\nVendor: Gamma LLC\nDate: 2024-03-10",
        "Invoice Number: INV-004\nTotal: $4,200.00\nVendor: Delta Ltd\nDate: 2024-04-05",
        "Invoice Number: INV-005\nTotal: $950.00\nVendor: Epsilon Co\nDate: 2024-05-12",
    ]

    # Mock LLM responses (label + schema discovery)
    mock_llm.return_value = MagicMock(text=json.dumps({
        "name": "Invoice",
        "description": "Standard invoices with vendor and amount",
        "keywords": ["invoice", "total", "vendor"],
        "fields": [
            {"name": "invoice_number", "type": "string", "description": "Invoice ID", "example": "INV-001"},
            {"name": "total_amount", "type": "number", "description": "Total due", "example": "1500"},
            {"name": "vendor_name", "type": "string", "description": "Vendor", "example": "Acme Corp"},
            {"name": "date", "type": "date", "description": "Invoice date", "example": "2024-01-15"},
        ]
    }))

    import tempfile
    td = tempfile.mkdtemp()
    files = []
    for i in range(5):
        fp = f"{td}/inv{i}.txt"
        with open(fp, "w") as fh:
            fh.write(f"placeholder {i}")  # text is mocked, just needs to exist
        files.append(fp)
    result = run_discovery(files=files, model="openai/test-model", min_cluster_size=2)

    assert isinstance(result, DiscoverResult)
    assert len(result.doc_names) == 5
    assert len(result.umap_coords) == 5
    assert len(result.doc_cluster_ids) == 5
    assert len(result.clusters) >= 1
    assert len(result.schemas) >= 1
    assert result.stats["total_docs"] == 5
    import shutil
    shutil.rmtree(td, ignore_errors=True)

    # Check schema has fields
    first_schema = list(result.schemas.values())[0]
    assert len(first_schema["fields"]) >= 1

    # Check cluster info
    first_cluster = result.clusters[0]
    assert "name" in first_cluster
    assert "description" in first_cluster
    assert first_cluster["doc_count"] > 0


# --- DiscoverResult dataclass ---

def test_discover_result_defaults():
    r = DiscoverResult()
    assert r.clusters == []
    assert r.schemas == {}
    assert r.umap_coords == []
    assert r.doc_names == []
    assert r.doc_cluster_ids == []
    assert r.stats == {}
    assert r.logs == []


# --- Field Name Normalization ---

def test_normalize_field_name_basic():
    assert _normalize_field_name("Invoice Number") == "invoice_number"


def test_normalize_field_name_camel_case():
    assert _normalize_field_name("invoiceNumber") == "invoice_number"
    assert _normalize_field_name("totalAmountDue") == "total_amount_due"


def test_normalize_field_name_hyphens_dots():
    assert _normalize_field_name("invoice-number") == "invoice_number"
    assert _normalize_field_name("vendor.name") == "vendor_name"


def test_normalize_field_name_special_chars():
    assert _normalize_field_name("amount ($)") == "amount"
    assert _normalize_field_name("  Tax %  ") == "tax"


def test_normalize_field_name_empty():
    assert _normalize_field_name("") == ""
    assert _normalize_field_name("   ") == ""


def test_normalize_field_name_already_snake():
    assert _normalize_field_name("invoice_number") == "invoice_number"


def test_normalize_field_name_multiple_underscores():
    assert _normalize_field_name("invoice__number") == "invoice_number"
    assert _normalize_field_name("__leading__trailing__") == "leading_trailing"


# --- Merge Field Lists ---

def test_merge_field_lists_new_fields():
    existing = [{"name": "name", "type": "string", "description": "Name"}]
    new = [{"name": "age", "type": "number", "description": "Age"}]
    merged = _merge_field_lists(existing, new)
    assert len(merged) == 2
    names = {f["name"] for f in merged}
    assert "name" in names
    assert "age" in names


def test_merge_field_lists_deduplicate():
    existing = [{"name": "invoice_number", "type": "string", "description": "ID"}]
    new = [{"name": "Invoice Number", "type": "string", "description": "A longer description of the field"}]
    merged = _merge_field_lists(existing, new)
    assert len(merged) == 1
    # Should pick the longer description
    assert "longer" in merged[0]["description"]


def test_merge_field_lists_prefer_specific_type():
    existing = [{"name": "amount", "type": "string", "description": "Amount"}]
    new = [{"name": "amount", "type": "number", "description": "Amount"}]
    merged = _merge_field_lists(existing, new)
    assert len(merged) == 1
    assert merged[0]["type"] == "number"


def test_merge_field_lists_skip_empty_names():
    existing = [{"name": "valid", "type": "string"}]
    new = [{"name": "", "type": "string"}, {"name": "also_valid", "type": "string"}]
    merged = _merge_field_lists(existing, new)
    names = {f["name"] for f in merged}
    assert "valid" in names
    assert "also_valid" in names
    assert "" not in names
    assert len(merged) == 2


def test_merge_field_lists_missing_name_key():
    """Fields with missing 'name' key in new_fields should be skipped."""
    existing = [{"name": "valid", "type": "string"}]
    new = [{"type": "string", "description": "No name"}, {"name": "good", "type": "string"}]
    merged = _merge_field_lists(existing, new)
    assert len(merged) == 2
    names = {f["name"] for f in merged}
    assert "valid" in names
    assert "good" in names


def test_merge_field_lists_existing_missing_name():
    """Existing fields with missing 'name' key should be skipped gracefully."""
    existing = [{"type": "string"}, {"name": "valid", "type": "string"}]
    new = [{"name": "new_field", "type": "number"}]
    merged = _merge_field_lists(existing, new)
    names = {f["name"] for f in merged}
    assert "valid" in names
    assert "new_field" in names


def test_merge_field_lists_collect_examples():
    existing = [{"name": "city", "type": "string", "example": "NYC"}]
    new = [{"name": "city", "type": "string", "example": "LA"}]
    merged = _merge_field_lists(existing, new)
    assert len(merged) == 1
    assert "examples" in merged[0]
    assert "NYC" in merged[0]["examples"]
    assert "LA" in merged[0]["examples"]


def test_merge_field_lists_empty_inputs():
    assert _merge_field_lists([], []) == []
    result = _merge_field_lists([], [{"name": "a", "type": "string"}])
    assert len(result) == 1


# --- Chunk for LLM ---

@patch("lakshana._utils.estimate_context_limit", return_value=10000)
def test_chunk_for_llm_short_text(mock_ctx):
    """Short text should return a single chunk."""
    result = _chunk_for_llm("Hello world", model="test-model", max_chars=6000)
    assert result == ["Hello world"]


def test_chunk_for_llm_empty():
    """Empty text should return empty list."""
    assert _chunk_for_llm("", model="test-model") == []
    assert _chunk_for_llm("   ", model="test-model") == []


@patch("lakshana._utils.estimate_context_limit", return_value=10000)
def test_chunk_for_llm_splits_long_text(mock_ctx):
    """Long text should be split into multiple chunks."""
    # Create a text that is definitely longer than max_chars
    text = "This is a sentence. " * 500  # ~10000 chars
    result = _chunk_for_llm(text, model="test-model", max_chars=2000)
    assert len(result) > 1
    # All content should be preserved (modulo whitespace stripping)
    combined = " ".join(result)
    # Original words should all appear
    assert combined.count("sentence") == 500


@patch("lakshana._utils.estimate_context_limit", return_value=10000)
def test_chunk_for_llm_respects_paragraph_boundaries(mock_ctx):
    """Chunks should try to split at paragraph boundaries."""
    para1 = "First paragraph content. " * 50
    para2 = "Second paragraph content. " * 50
    text = para1 + "\n\n" + para2
    result = _chunk_for_llm(text, model="test-model", max_chars=1500)
    assert len(result) >= 2


@patch("lakshana._utils.estimate_context_limit", return_value=10000)
def test_chunk_for_llm_no_data_loss(mock_ctx):
    """Every word from the original text should appear in some chunk."""
    words = [f"word{i}" for i in range(300)]
    text = " ".join(words)
    result = _chunk_for_llm(text, model="test-model", max_chars=500)
    combined = " ".join(result)
    for w in words:
        assert w in combined, f"Lost word: {w}"


# --- CSV Export Edge Cases ---

def test_export_csv_headers_empty():
    csv_out = export_as_csv_headers({"fields": []})
    assert csv_out.strip() == ""


def test_export_csv_headers_with_commas_in_example():
    schema = {
        "fields": [
            {"name": "address", "type": "string", "example": "123 Main St, Suite 4"},
        ]
    }
    csv_out = export_as_csv_headers(schema)
    lines = csv_out.strip().split("\n")
    assert lines[0] == "address"
    # The example with comma should be properly quoted
    assert "123 Main St" in lines[1]


def test_export_csv_headers_with_quotes_in_example():
    schema = {
        "fields": [
            {"name": "description", "type": "string", "example": 'A "great" product'},
        ]
    }
    csv_out = export_as_csv_headers(schema)
    # Quotes should be escaped as double-quotes in CSV
    assert '""great""' in csv_out


# --- LLM failure resilience ---

@patch("lakshana.core.call_llm")
def test_label_cluster_llm_failure(mock_llm):
    """When LLM fails on both attempts, should return fallback label."""
    mock_llm.side_effect = Exception("API error")
    texts = ["Some doc text"]
    result = label_cluster(texts, model="test-model")
    assert result["name"] == "Unknown Type"
    assert "keywords" in result


@patch("lakshana.core.call_llm")
def test_discover_schema_empty_texts(mock_llm):
    """Schema discovery with empty text list should handle gracefully."""
    mock_llm.return_value = MagicMock(text=json.dumps({"fields": []}))
    result = discover_schema_for_cluster([], [], model="test-model")
    assert result == {"fields": []}


@patch("lakshana.core.call_llm")
def test_discover_schema_llm_returns_invalid_json(mock_llm):
    """LLM returning garbage should not crash — should retry and log."""
    # First call returns garbage, second returns valid JSON
    mock_llm.side_effect = [
        MagicMock(text="this is not json"),
        MagicMock(text=json.dumps({
            "fields": [{"name": "test_field", "type": "string", "description": "A field", "example": "val"}]
        })),
        # Verification calls
        MagicMock(text=json.dumps({
            "found": [{"name": "test_field", "present": True, "value": "val"}]
        })),
    ]
    texts = ["Document with test_field: some value"]
    result = discover_schema_for_cluster(texts, ["doc1.txt"], model="test-model", max_samples=1, max_verify=1)
    assert "fields" in result


# --- Run discovery edge cases ---

@patch("lakshana.core.call_llm")
@patch("lakshana.core.extract_text_from_file")
def test_run_discovery_single_file(mock_extract, mock_llm):
    """Discovery with fewer than 2 docs should return early."""
    mock_extract.return_value = "Some text content"
    import tempfile, os
    td = tempfile.mkdtemp()
    fp = os.path.join(td, "single.txt"); open(fp, "w").write("placeholder")
    files = [fp]
    result = run_discovery(files=files, model="test-model")
    assert isinstance(result, DiscoverResult)
    # Should log a message about needing at least 2 docs
    assert any("at least 2" in log for log in result.logs)


@patch("lakshana.core.call_llm")
@patch("lakshana.core.extract_text_from_file")
def test_run_discovery_all_files_fail(mock_extract, mock_llm):
    """When all files fail to parse, should return early."""
    mock_extract.side_effect = Exception("File read error")
    import tempfile, os
    td = tempfile.mkdtemp()
    files = []
    for n in ("bad1.txt", "bad2.txt"):
        fp = os.path.join(td, n); open(fp, "w").write("placeholder")
        files.append(fp)
    result = run_discovery(files=files, model="test-model")
    assert isinstance(result, DiscoverResult)
    assert len(result.doc_names) == 0


@patch("lakshana.core.call_llm")
@patch("lakshana.core.extract_text_from_file")
def test_run_discovery_progress_callback(mock_extract, mock_llm):
    """Progress callback should be called during discovery."""
    mock_extract.side_effect = [
        "Invoice Number: INV-001\nTotal: $1,500.00",
        "Invoice Number: INV-002\nTotal: $2,300.00",
        "Invoice Number: INV-003\nTotal: $800.00",
    ]
    mock_llm.return_value = MagicMock(text=json.dumps({
        "name": "Invoice",
        "fields": [{"name": "invoice_number", "type": "string", "description": "ID", "example": "INV-001"}],
        "found": [{"name": "invoice_number", "present": True, "value": "INV-001"}],
    }))

    progress_calls = []
    def on_progress(stage, msg, pct):
        progress_calls.append((stage, msg, pct))

    import tempfile, os
    td = tempfile.mkdtemp()
    files = []
    for i in range(3):
        fp = os.path.join(td, f"inv{i}.txt"); open(fp, "w").write("placeholder")
        files.append(fp)
    run_discovery(files=files, model="openai/test-model", on_progress=on_progress)
    assert len(progress_calls) > 0
    stages = {c[0] for c in progress_calls}
    assert "parse" in stages


# --- Structural fingerprint consistency ---

def test_structural_fingerprint_consistent_length():
    """All fingerprints should have the same length regardless of input."""
    fp1 = structural_fingerprint("")
    fp2 = structural_fingerprint("Short")
    fp3 = structural_fingerprint("A " * 10000)
    assert len(fp1) == len(fp2) == len(fp3)


def test_structural_fingerprint_tables():
    """Table-like content should set has_table flag."""
    text = "Col1\tCol2\tCol3\nVal1\tVal2\tVal3"
    fp = structural_fingerprint(text)
    # has_table is at index 15
    assert fp[15] == 1.0


def test_structural_fingerprint_urls():
    text = "Visit https://example.com for more info"
    fp = structural_fingerprint(text)
    # URL density should be > 0
    assert fp[7] > 0  # URL density is 5th in the density features block (index 7)


def test_structural_fingerprint_emails():
    text = "Contact: user@example.com\nCC: admin@example.com"
    fp = structural_fingerprint(text)
    # has_email is at index 14
    assert fp[14] == 1.0


# --- Levenshtein Distance ---

def test_levenshtein_identical():
    assert _levenshtein("hello", "hello") == 0


def test_levenshtein_one_change():
    assert _levenshtein("total", "totals") == 1
    assert _levenshtein("date", "data") == 1


def test_levenshtein_similar():
    assert _levenshtein("total", "total_amount") < 8
    assert _levenshtein("amt", "amount") == 3


def test_levenshtein_empty():
    assert _levenshtein("", "") == 0
    assert _levenshtein("abc", "") == 3
    assert _levenshtein("", "xyz") == 3


# --- Suggest Merges ---

def test_suggest_merges_similar_names():
    fields = [
        {"name": "total", "type": "number", "description": "Total amount due"},
        {"name": "total_amount", "type": "number", "description": "Total amount due"},
    ]
    suggestions = suggest_merges(fields)
    assert len(suggestions) >= 1
    assert "total" in suggestions[0]["fields"]
    assert "total_amount" in suggestions[0]["fields"]
    assert suggestions[0]["suggested_name"] == "total_amount"  # longer name preferred


def test_suggest_merges_no_duplicates():
    fields = [
        {"name": "vendor_name", "type": "string", "description": "Vendor"},
        {"name": "invoice_date", "type": "date", "description": "Date of invoice"},
    ]
    suggestions = suggest_merges(fields)
    assert len(suggestions) == 0


def test_suggest_merges_empty():
    assert suggest_merges([]) == []
    assert suggest_merges([{"name": "solo"}]) == []


def test_suggest_merges_description_overlap():
    fields = [
        {"name": "client_name", "type": "string", "description": "The name of the customer who ordered"},
        {"name": "customer", "type": "string", "description": "The customer who placed the order"},
    ]
    suggestions = suggest_merges(fields)
    # "customer" is contained in "client_name"? No. But descriptions have overlap
    # depends on exact overlap ratio — this tests the function doesn't crash
    assert isinstance(suggestions, list)


def test_suggest_merges_name_containment():
    fields = [
        {"name": "amount", "type": "number", "description": "Amount"},
        {"name": "total_amount", "type": "number", "description": "Total amount"},
    ]
    suggestions = suggest_merges(fields)
    assert len(suggestions) >= 1
    assert any("amount" in s["fields"] for s in suggestions)


# --- Deduplicate Fields ---

@patch("lakshana.core.call_llm")
def test_deduplicate_fields_merges(mock_llm):
    mock_llm.return_value = MagicMock(text=json.dumps({
        "groups": [
            {"canonical": "customer_name", "aliases": ["client_name", "buyer_name"], "reason": "Same concept"}
        ]
    }))

    fields = [
        {"name": "customer_name", "type": "string", "description": "Customer", "example": "Acme", "frequency": 80},
        {"name": "client_name", "type": "string", "description": "Client name", "example": "Beta Inc", "frequency": 60},
        {"name": "buyer_name", "type": "string", "description": "Buyer", "example": "Gamma", "frequency": 40},
        {"name": "invoice_date", "type": "date", "description": "Date", "example": "2024-01-01", "frequency": 90},
    ]
    result = deduplicate_fields(fields, model="test-model")
    names = [f["name"] for f in result]
    assert "customer_name" in names
    assert "client_name" not in names
    assert "buyer_name" not in names
    assert "invoice_date" in names
    # Check aliases are present
    customer = next(f for f in result if f["name"] == "customer_name")
    assert "aliases" in customer
    assert "client_name" in customer["aliases"] or "buyer_name" in customer["aliases"]


@patch("lakshana.core.call_llm")
def test_deduplicate_fields_no_duplicates(mock_llm):
    mock_llm.return_value = MagicMock(text=json.dumps({"groups": []}))

    fields = [
        {"name": "vendor", "type": "string", "description": "Vendor"},
        {"name": "date", "type": "date", "description": "Date"},
    ]
    result = deduplicate_fields(fields, model="test-model")
    assert len(result) == 2


@patch("lakshana.core.call_llm")
def test_deduplicate_fields_llm_failure(mock_llm):
    mock_llm.side_effect = Exception("API error")
    fields = [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}]
    result = deduplicate_fields(fields, model="test-model")
    # Should return original fields on failure
    assert len(result) == 2


def test_deduplicate_fields_empty():
    assert deduplicate_fields([], model="test") == []
    assert deduplicate_fields([{"name": "only"}], model="test") == [{"name": "only"}]


# --- Group Fields ---

@patch("lakshana.core.call_llm")
def test_group_fields_basic(mock_llm):
    mock_llm.return_value = MagicMock(text=json.dumps({
        "groups": [
            {"name": "Vendor Info", "description": "Vendor details", "fields": ["vendor_name", "vendor_address"]},
            {"name": "Invoice Details", "description": "Invoice metadata", "fields": ["invoice_number", "invoice_date"]},
        ]
    }))

    fields = [
        {"name": "vendor_name", "type": "string"},
        {"name": "vendor_address", "type": "string"},
        {"name": "invoice_number", "type": "string"},
        {"name": "invoice_date", "type": "date"},
    ]
    updated_fields, groups = group_fields(fields, model="test-model")

    assert len(groups) == 2
    assert groups[0]["name"] == "Vendor Info"
    assert groups[0]["color"] == GROUP_COLORS[0]
    assert groups[1]["name"] == "Invoice Details"
    assert groups[1]["color"] == GROUP_COLORS[1]

    # Check fields got group property
    for f in updated_fields:
        assert "group" in f
    vendor_field = next(f for f in updated_fields if f["name"] == "vendor_name")
    assert vendor_field["group"] == "Vendor Info"


@patch("lakshana.core.call_llm")
def test_group_fields_with_ungrouped(mock_llm):
    mock_llm.return_value = MagicMock(text=json.dumps({
        "groups": [
            {"name": "Vendor", "description": "Vendor info", "fields": ["vendor_name"]},
        ]
    }))

    fields = [
        {"name": "vendor_name", "type": "string"},
        {"name": "random_field", "type": "string"},
    ]
    updated_fields, groups = group_fields(fields, model="test-model")

    # Should have 2 groups: Vendor + Ungrouped
    assert len(groups) == 2
    assert any(g["name"] == "Ungrouped" for g in groups)
    random_f = next(f for f in updated_fields if f["name"] == "random_field")
    assert random_f["group"] == "Ungrouped"


@patch("lakshana.core.call_llm")
def test_group_fields_llm_failure(mock_llm):
    mock_llm.side_effect = Exception("API error")
    fields = [{"name": "a", "type": "string"}]
    updated_fields, groups = group_fields(fields, model="test-model")
    assert updated_fields == [{"name": "a", "type": "string"}]
    assert groups == []


def test_group_fields_empty():
    updated_fields, groups = group_fields([], model="test")
    assert updated_fields == []
    assert groups == []


@patch("lakshana.core.call_llm")
def test_group_fields_handles_bare_list_response(mock_llm):
    """Regression: some LLMs return a top-level JSON array instead of {"groups": [...]}.

    Before the fix, this crashed the legacy path with
    `AttributeError: 'list' object has no attribute 'get'`.
    """
    mock_llm.return_value = MagicMock(text=json.dumps([
        {"name": "Header", "description": "Top of doc", "fields": ["a", "b"]},
        {"name": "Body", "description": "Middle", "fields": ["c"]},
    ]))
    fields = [
        {"name": "a", "type": "string"},
        {"name": "b", "type": "string"},
        {"name": "c", "type": "string"},
    ]
    updated_fields, groups = group_fields(fields, model="test-model")
    group_names = [g["name"] for g in groups]
    assert "Header" in group_names
    assert "Body" in group_names


@patch("lakshana.core.call_llm")
def test_group_fields_repeating(mock_llm):
    mock_llm.return_value = MagicMock(text=json.dumps({
        "groups": [
            {"name": "Line Items", "description": "Repeating rows", "fields": ["item_name", "quantity"], "is_repeating": True},
        ]
    }))

    fields = [
        {"name": "item_name", "type": "string"},
        {"name": "quantity", "type": "number"},
    ]
    updated_fields, groups = group_fields(fields, model="test-model")
    assert any(g.get("is_repeating") for g in groups)


# --- Sub-Cluster Detection ---

def test_detect_subclusters_small_clusters():
    """Clusters with <=8 docs should not be sub-clustered."""
    embeddings = np.random.randn(6, 10).astype("float32")
    labels = np.array([0, 0, 0, 0, 0, 0])
    result = detect_subclusters(embeddings, labels)
    assert result == {}  # 6 docs, not > 8


def test_detect_subclusters_large_cluster():
    """Large cluster with clear sub-groups should find sub-clusters."""
    np.random.seed(42)
    # 2 clear sub-groups within one cluster
    group_a = np.random.randn(6, 50).astype("float32") + 10
    group_b = np.random.randn(6, 50).astype("float32") - 10
    embeddings = np.vstack([group_a, group_b])
    labels = np.zeros(12, dtype=int)  # All same cluster (id=0), >8 docs
    result = detect_subclusters(embeddings, labels, min_size=2)
    # May or may not find sub-clusters depending on HDBSCAN behavior
    assert isinstance(result, dict)
    if 0 in result:
        for sub in result[0]:
            assert "name" in sub
            assert "doc_indices" in sub
            assert "doc_count" in sub


def test_detect_subclusters_empty():
    embeddings = np.array([]).reshape(0, 10).astype("float32")
    labels = np.array([], dtype=int)
    result = detect_subclusters(embeddings, labels)
    assert result == {}


# --- Cross-Cluster Field Linking ---

def test_find_cross_cluster_fields_basic():
    schemas = {
        "0": {"fields": [
            {"name": "company_name", "type": "string", "frequency": 90},
            {"name": "date", "type": "date", "frequency": 85},
            {"name": "invoice_number", "type": "string", "frequency": 80},
        ]},
        "1": {"fields": [
            {"name": "company_name", "type": "string", "frequency": 80},
            {"name": "date", "type": "date", "frequency": 75},
            {"name": "report_id", "type": "string", "frequency": 70},
        ]},
    }
    result = find_cross_cluster_fields(schemas)
    assert len(result) == 2  # company_name and date are shared
    names = [r["name"] for r in result]
    assert "company_name" in names
    assert "date" in names

    company = next(r for r in result if r["name"] == "company_name")
    assert len(company["clusters"]) == 2
    assert company["avg_frequency"] == 85.0


def test_find_cross_cluster_fields_no_overlap():
    schemas = {
        "0": {"fields": [{"name": "invoice_number", "frequency": 90}]},
        "1": {"fields": [{"name": "report_id", "frequency": 80}]},
    }
    result = find_cross_cluster_fields(schemas)
    assert result == []


def test_find_cross_cluster_fields_empty():
    assert find_cross_cluster_fields({}) == []
    assert find_cross_cluster_fields({"0": {"fields": []}}) == []


# --- Grounded Verification ---

@patch("lakshana.core.call_llm")
def test_discover_schema_grounding(mock_llm):
    """Verification should track grounded_count."""
    # Discovery call returns fields
    discovery_response = MagicMock(text=json.dumps({
        "fields": [
            {"name": "invoice_number", "type": "string", "description": "Invoice ID", "example": "INV-001"},
        ]
    }))
    # Verification call returns grounded data
    verify_response = MagicMock(text=json.dumps({
        "found": [
            {"name": "invoice_number", "value": "INV-001", "present": True, "quote": "Invoice Number: INV-001", "grounded": True},
        ]
    }))
    mock_llm.side_effect = [discovery_response, verify_response]

    texts = ["Invoice Number: INV-001\nTotal: $1,500.00"]
    result = discover_schema_for_cluster(texts, ["doc1.txt"], model="test-model", max_samples=1, max_verify=1)

    assert "fields" in result
    if result["fields"]:
        inv_field = next((f for f in result["fields"] if f["name"] == "invoice_number"), None)
        if inv_field:
            assert "grounded_count" in inv_field


# --- Robustness: input validation in run_discovery ---

def test_run_discovery_rejects_non_list_files():
    import pytest
    with pytest.raises(TypeError, match="must be a list"):
        run_discovery(files="not-a-list", model="openai/test-model")


def test_run_discovery_rejects_empty_list():
    import pytest
    with pytest.raises(ValueError, match="empty"):
        run_discovery(files=[], model="openai/test-model")


def test_run_discovery_rejects_non_string_entries():
    import pytest
    with pytest.raises(TypeError, match="must be str"):
        run_discovery(files=[123, 456], model="openai/test-model")


def test_run_discovery_rejects_missing_files():
    import pytest
    with pytest.raises(FileNotFoundError, match="do not exist"):
        run_discovery(files=["/this/path/does/not/exist.txt"], model="openai/test-model")


def test_run_discovery_rejects_invalid_min_cluster_size():
    import pytest
    import tempfile, os
    td = tempfile.mkdtemp()
    fp = os.path.join(td, "a.txt"); open(fp, "w").write("x")
    with pytest.raises(ValueError, match="min_cluster_size must be"):
        run_discovery(files=[fp], min_cluster_size=1, model="openai/test-model")
    with pytest.raises(ValueError, match="min_cluster_size must be"):
        run_discovery(files=[fp], min_cluster_size=0, model="openai/test-model")


# --- Robustness: discover_from_strings convenience helper ---

def test_discover_from_strings_rejects_non_list():
    from lakshana import discover_from_strings
    import pytest
    with pytest.raises(TypeError, match="must be a list"):
        discover_from_strings(texts="single string", model="openai/test-model")


def test_discover_from_strings_rejects_empty():
    from lakshana import discover_from_strings
    import pytest
    with pytest.raises(ValueError, match="empty"):
        discover_from_strings(texts=[], model="openai/test-model")


def test_discover_from_strings_rejects_non_strings():
    from lakshana import discover_from_strings
    import pytest
    with pytest.raises(TypeError, match="must be str"):
        discover_from_strings(texts=["ok", 42, None], model="openai/test-model")


def test_discover_from_strings_rejects_mismatched_names():
    from lakshana import discover_from_strings
    import pytest
    with pytest.raises(ValueError, match="length"):
        discover_from_strings(
            texts=["a", "b", "c"],
            names=["only-two", "names"],
            model="openai/test-model",
        )


@patch("lakshana.core.call_llm")
def test_discover_from_strings_writes_tempfiles_and_runs(mock_llm):
    from lakshana import discover_from_strings
    mock_llm.return_value = MagicMock(text=json.dumps({
        "name": "Invoice",
        "fields": [{"name": "invoice_number", "type": "string", "description": "ID", "example": "INV-001"}],
        "found": [{"name": "invoice_number", "present": True, "value": "INV-001"}],
    }))
    texts = [f"Invoice {i}\nTotal: $100" for i in range(4)]
    result = discover_from_strings(texts=texts, model="openai/test-model", min_cluster_size=2)
    assert isinstance(result, DiscoverResult)
    assert result.stats["n_input_files"] == 4
    assert result.stats["total_docs"] >= 1


# --- Robustness: structural_fingerprint on empty input ---

def test_structural_fingerprint_empty_is_all_zero():
    """Empty input must produce an all-zero vector, not a phantom paragraph flag."""
    fp = structural_fingerprint("")
    assert len(fp) == 18
    assert all(v == 0.0 for v in fp), f"Expected all zeros, got {fp}"


def test_structural_fingerprint_single_char_no_phantom_paragraphs():
    """A 1-char doc has no paragraph break; the paragraph density feature must be 0."""
    fp = structural_fingerprint("x")
    # Feature index 11 is the paragraph density
    assert fp[11] == 0.0, f"Expected paragraph feature 0 for single-char input, got {fp[11]}"


# --- Robustness: result.stats populated even on partial runs ---

@patch("lakshana.core.extract_text_from_file")
def test_run_discovery_populates_stats_on_too_few_parsed(mock_extract):
    """Even when most files fail to parse, stats should be populated with diagnostics."""
    mock_extract.return_value = ""  # every file extracts to empty
    import tempfile, os
    td = tempfile.mkdtemp()
    files = []
    for i in range(3):
        fp = os.path.join(td, f"f{i}.txt"); open(fp, "w").write("placeholder")
        files.append(fp)
    result = run_discovery(files=files, model="openai/test-model", min_cluster_size=2)
    assert result.stats["n_input_files"] == 3
    assert result.stats["total_docs"] == 0
    assert result.stats["parsed_errors"] == 3
    assert "warning" in result.stats  # diagnostic so user knows why clusters=0
    assert "duration_s" in result.stats


# --- Robustness: deduplicate_fields surfaces config errors ---

def test_deduplicate_fields_surfaces_missing_api_key():
    """Missing API key is a configuration error, must NOT be silently swallowed."""
    import pytest
    import os
    # Clear all provider keys so call_llm has nothing to use
    saved = {}
    for k in ("OPENAI_API_KEY","GROQ_API_KEY","ANTHROPIC_API_KEY","CEREBRAS_API_KEY","GOOGLE_API_KEY","OPENROUTER_API_KEY"):
        saved[k] = os.environ.pop(k, None)
    try:
        with pytest.raises(ValueError, match="No API key"):
            deduplicate_fields(
                [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}],
                model="openai/test-model",
            )
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
