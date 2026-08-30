#!/usr/bin/env python3
"""Build compact task packets or validate bounded task-result summaries."""

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parents[1]))

from scripts.toolkit.task_packets import (
    build_task_packet,
    validate_task_result_summary,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "result"))
    parser.add_argument("document", type=Path)
    args = parser.parse_args()
    try:
        document = json.loads(args.document.read_text(encoding="utf-8"))
        output = (
            build_task_packet(document)
            if args.mode == "build"
            else validate_task_result_summary(document)
        )
    except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {"status": "blocked", "code": "INVALID_TASK_PACKET", "detail": str(error)[:128]},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
