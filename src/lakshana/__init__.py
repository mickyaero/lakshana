"""Lakshana — zero-config schema discovery for document collections.

Drop a folder of PDFs, get a JSON Schema. No training, no labels, no manual
schema design.

Quickstart::

    from lakshana import discover

    result = discover(
        files=["./docs/inv1.pdf", "./docs/inv2.pdf"],
        model="groq/llama-3.3-70b-versatile",
        min_cluster_size=3,
    )
    for cluster in result.clusters:
        schema = result.schemas[str(cluster["id"])]
        print(cluster["name"], [f["name"] for f in schema["fields"]])
"""

import logging as _logging

from lakshana.core import (
    DiscoverResult,
    cluster_documents,
    deduplicate_fields,
    detect_subclusters,
    discover_from_strings,
    discover_schema_for_cluster,
    embed_documents,
    export_as_csv_headers,
    export_as_json_schema,
    export_as_markdown,
    export_as_structure_entities,
    find_cross_cluster_fields,
    group_fields,
    label_cluster,
    run_discovery as discover,
    structural_fingerprint,
    suggest_merges,
)


def set_log_level(level):
    """Set the log level for every ``lakshana.*`` logger.

    Accepts either an int (``logging.INFO``) or a string (``"INFO"``,
    ``"WARNING"``, ``"DEBUG"``, ``"ERROR"``, ``"CRITICAL"``). Useful
    when embedding Lakshana inside an app that wants to silence its
    progress messages, or surface its DEBUG details during triage.
    """
    if isinstance(level, str):
        level = level.upper()
    _logging.getLogger("lakshana").setLevel(level)

__version__ = "0.1.3"

__all__ = [
    "DiscoverResult",
    "__version__",
    "cluster_documents",
    "deduplicate_fields",
    "detect_subclusters",
    "discover",
    "discover_from_strings",
    "discover_schema_for_cluster",
    "embed_documents",
    "export_as_csv_headers",
    "export_as_json_schema",
    "export_as_markdown",
    "export_as_structure_entities",
    "find_cross_cluster_fields",
    "group_fields",
    "label_cluster",
    "set_log_level",
    "structural_fingerprint",
    "suggest_merges",
]
