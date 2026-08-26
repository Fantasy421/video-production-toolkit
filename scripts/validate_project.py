#!/usr/bin/env python3
"""Print deterministic structural validation for one runtime project."""

import argparse
import json
from pathlib import Path

try:
    from scripts.toolkit.validation import validate_project
except ModuleNotFoundError:
    from toolkit.validation import validate_project


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a video-toolkit project structurally.")
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    result = validate_project(args.root)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(bool(result["errors"]))


if __name__ == "__main__":
    main()
