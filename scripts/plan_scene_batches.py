#!/usr/bin/env python3
"""Plan clean chapter-local scene batches from frozen timing metadata."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.toolkit.scene_batches import plan_scene_batches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contracts", type=Path)
    parser.add_argument("timing", type=Path)
    args = parser.parse_args()
    try:
        contracts = json.loads(args.contracts.read_text(encoding="utf-8"))
        timing = json.loads(args.timing.read_text(encoding="utf-8"))
        batches = plan_scene_batches(contracts, timing)
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "blocked", "code": "SCENE_BATCH_PLAN_INVALID", "detail": str(error)[:128]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(batches, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
