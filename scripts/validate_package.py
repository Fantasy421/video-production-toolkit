import json
from pathlib import Path


REQUIRED = (
    ".codex-plugin/plugin.json",
    "agents/openai.yaml",
    "assets/project-template/project.json",
    "assets/project-template/review-pack/index.html",
    "skills/video-director/SKILL.md",
)


def validate_package(root: Path) -> list[str]:
    errors = [f"missing:{path}" for path in REQUIRED if not (root / path).is_file()]
    manifest_path = root / ".codex-plugin/plugin.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("id") != "video-production-toolkit":
            errors.append("invalid:plugin-id")
        if manifest.get("name") != "video-production-toolkit":
            errors.append("invalid:plugin-name")
        if manifest.get("skills") != "./skills/":
            errors.append("invalid:skills-path")
    return errors


if __name__ == "__main__":
    import sys

    issues = validate_package(Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve())
    print("\n".join(issues) if issues else "package valid")
    raise SystemExit(bool(issues))
