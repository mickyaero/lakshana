"""Command-line interface for Lakshana.

Usage::

    lakshana analyze ./docs --model groq/llama-3.3-70b-versatile --output result.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from lakshana import __version__, discover
from lakshana.ingest import get_supported_files


def _progress(stage: str, msg: str, pct: int) -> None:
    print(f"[{pct:3d}%] {stage:>10} | {msg}", file=sys.stderr)


def _cmd_analyze(args: argparse.Namespace) -> int:
    directory = Path(args.path)
    if not directory.exists():
        print(f"error: path does not exist: {directory}", file=sys.stderr)
        return 2

    if directory.is_dir():
        files = get_supported_files(str(directory))
    elif directory.is_file():
        files = [str(directory)]
    else:
        print(f"error: not a file or directory: {directory}", file=sys.stderr)
        return 2

    if not files:
        print(f"error: no supported files found in {directory}", file=sys.stderr)
        return 2

    print(f"discovering schemas across {len(files)} file(s) with {args.model}...", file=sys.stderr)
    result = discover(
        files=files,
        model=args.model,
        min_cluster_size=args.min_cluster_size,
        on_progress=_progress if not args.quiet else None,
    )

    payload = {
        "stats": result.stats,
        "clusters": result.clusters,
        "schemas": result.schemas,
        "doc_names": result.doc_names,
        "doc_cluster_ids": list(result.doc_cluster_ids),
    }
    text = json.dumps(payload, indent=2, default=str)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)

    print(
        f"done: {result.stats.get('clusters', 0)} cluster(s), "
        f"{result.stats.get('total_fields', 0)} field(s), "
        f"{result.stats.get('duration_s', 0):.1f}s",
        file=sys.stderr,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lakshana",
        description="Zero-config schema discovery for document collections.",
    )
    p.add_argument("--version", action="version", version=f"lakshana {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    a = sub.add_parser("analyze", help="Discover schemas in a folder of documents.")
    a.add_argument("path", help="Directory of documents (or a single file).")
    a.add_argument(
        "--model", "-m",
        default="groq/llama-3.3-70b-versatile",
        help="LLM model id, e.g. 'groq/llama-3.3-70b-versatile', 'claude-sonnet-4-6', 'gpt-4o-mini'.",
    )
    a.add_argument(
        "--min-cluster-size", "-k",
        type=int, default=3,
        help="Minimum number of documents per cluster (default: 3).",
    )
    a.add_argument(
        "--output", "-o",
        help="Write JSON result to this file (default: stdout).",
    )
    a.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output.")
    a.set_defaults(func=_cmd_analyze)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
