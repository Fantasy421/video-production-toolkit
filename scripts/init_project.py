"""Initialize a recoverable video-production toolkit project."""

import argparse
from pathlib import Path

from toolkit.project_state import initialize_project


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workflow", default="knowledge-video")
    arguments = parser.parse_args()

    state = initialize_project(arguments.target, arguments.project_id, arguments.workflow)
    print((arguments.target.resolve() / "project.json"))
    print(state["project_id"])


if __name__ == "__main__":
    main()
