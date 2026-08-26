#!/usr/bin/env python3
"""Command-line access to compact creative-registry candidate search."""

import argparse
import json
from pathlib import Path

try:  # Supports both ``python -m`` and direct script execution.
    from scripts.toolkit.registry import search_registry
except ModuleNotFoundError:
    from toolkit.registry import search_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Search compact creative registry metadata.")
    parser.add_argument("kind")
    parser.add_argument("query", help="JSON object with registry query fields")
    parser.add_argument("--root", type=Path, default=Path(__file__).parents[1])
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    try:
        query = json.loads(args.query)
    except json.JSONDecodeError as error:
        parser.error(f"query must be valid JSON: {error.msg}")
    print(json.dumps(search_registry(args.root.resolve(), args.kind, query, args.limit), ensure_ascii=False))


if __name__ == "__main__":
    main()
