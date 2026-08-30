#!/usr/bin/env python3
"""Validate one scene-batch media manifest and emit compact JSON only."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.toolkit.batch_media_validation import validate_media_batch_json


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        contents = args.manifest.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        contents = ""
    result = validate_media_batch_json(args.project, contents)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
