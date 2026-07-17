from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
FEATURE_ROOT = DOCS / "features"
CHANGE_ROOT = DOCS / "changes" / "unreleased"
REGISTRY_PATH = DOCS / "feature-registry.json"
OPENAPI_DIR = DOCS / "openapi"
FEATURE_ID_RE = re.compile(r"^[A-Z][A-Z0-9]*-[A-Z][A-Z0-9-]*-\d{3}$")
REQUIRED_FEATURE_FIELDS = {
    "feature_id",
    "title",
    "module",
    "status",
    "apis",
    "code",
    "tests",
    "depends_on",
    "last_verified_version",
    "last_verified_date",
}
REQUIRED_FEATURE_SECTIONS = (
    "Purpose and user entry",
    "UI and behavior",
    "API contract",
    "Data, routing and read-only constraints",
    "Business rules and units",
    "Loading, empty and failure behavior",
    "Code and dependencies",
    "Tests and acceptance",
    "Compatibility and deprecation",
)
REQUIRED_CHANGE_FIELDS = {"change_id", "features", "change_type", "status", "compatibility"}
REQUIRED_CHANGE_SECTIONS = (
    "Before and after",
    "Impact",
    "Documentation updated",
    "Verification",
    "Deployment and rollback",
)


class GovernanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class Document:
    path: Path
    metadata: dict[str, Any]
    body: str


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value in {"[]", "{}"}:
        return json.loads(value)
    if value.startswith("[") or value.startswith("{"):
        return json.loads(value)
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def read_document(path: Path) -> Document:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise GovernanceError(f"{relative(path)}: missing front matter")
    try:
        header, body = text[4:].split("\n---\n", 1)
    except ValueError as exc:
        raise GovernanceError(f"{relative(path)}: unterminated front matter") from exc
    metadata: dict[str, Any] = {}
    for line in header.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise GovernanceError(f"{relative(path)}: invalid front matter line: {line}")
        key, value = line.split(":", 1)
        metadata[key.strip()] = parse_scalar(value)
    return Document(path=path, metadata=metadata, body=body)


def feature_documents() -> list[Document]:
    paths = sorted(path for path in FEATURE_ROOT.rglob("*.md") if path.name != "_template.md")
    return [read_document(path) for path in paths]


def change_documents() -> list[Document]:
    return [read_document(path) for path in sorted(CHANGE_ROOT.glob("*.md"))]


def validate_sections(document: Document, sections: tuple[str, ...]) -> list[str]:
    return [f"{relative(document.path)}: missing section '## {section}'" for section in sections if f"## {section}" not in document.body]


def build_registry() -> dict[str, Any]:
    errors: list[str] = []
    features: list[dict[str, Any]] = []
    seen: set[str] = set()
    for document in feature_documents():
        missing = REQUIRED_FEATURE_FIELDS - document.metadata.keys()
        if missing:
            errors.append(f"{relative(document.path)}: missing metadata {sorted(missing)}")
            continue
        feature_id = str(document.metadata["feature_id"])
        if not FEATURE_ID_RE.fullmatch(feature_id):
            errors.append(f"{relative(document.path)}: invalid feature_id {feature_id}")
        if feature_id in seen:
            errors.append(f"{relative(document.path)}: duplicate feature_id {feature_id}")
        seen.add(feature_id)
        errors.extend(validate_sections(document, REQUIRED_FEATURE_SECTIONS))
        item = dict(document.metadata)
        item["document"] = relative(document.path)
        features.append(item)
    for item in features:
        for dependency in item["depends_on"]:
            if dependency not in seen:
                errors.append(f"{item['document']}: unknown dependency {dependency}")
        for key in ("apis", "code", "tests", "depends_on"):
            if not isinstance(item[key], list):
                errors.append(f"{item['document']}: {key} must be a list")
    if errors:
        raise GovernanceError("\n".join(errors))
    features.sort(key=lambda item: item["feature_id"])
    source = json.dumps(features, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    import hashlib

    return {
        "schemaVersion": 1,
        "registryVersion": hashlib.sha256(source.encode("utf-8")).hexdigest()[:12],
        "features": features,
    }


def write_or_check(path: Path, payload: Any, check: bool) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
    if check:
        if not path.is_file() or path.read_text(encoding="utf-8") != content:
            raise GovernanceError(f"{relative(path)} is stale; regenerate it")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def git_lines(*args: str, allow_failure: bool = False) -> list[str]:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, encoding="utf-8", errors="replace", capture_output=True, check=False
    )
    if result.returncode and not allow_failure:
        raise GovernanceError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def changed_paths(base: str | None = None) -> set[str]:
    if base:
        return set(git_lines("diff", "--name-only", f"{base}...HEAD"))
    paths = set(git_lines("diff", "--name-only", "HEAD"))
    paths.update(git_lines("ls-files", "--others", "--exclude-standard"))
    if not paths:
        paths.update(git_lines("diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD", allow_failure=True))
    return {path.replace("\\", "/") for path in paths}


def validate_changes(paths: set[str], registry: dict[str, Any]) -> None:
    errors: list[str] = []
    feature_by_id = {item["feature_id"]: item for item in registry["features"]}
    changed_records = [doc for doc in change_documents() if relative(doc.path) in paths]
    changed_feature_docs = {relative(doc.path) for doc in feature_documents() if relative(doc.path) in paths}
    map_payload = json.loads((DOCS / "impact-map.json").read_text(encoding="utf-8"))
    ignored = tuple(map_payload["ignored_paths"])
    functional_paths = {
        path
        for path in paths
        if not path.startswith(ignored)
        and not path.startswith("docs/")
        and not Path(path).name.startswith("test_")
        and not Path(path).name.endswith((".spec.ts", ".test.ts", ".spec.js", ".test.js"))
        and path not in {"VERSION", "pyproject.toml", "frontend/package.json"}
    }
    declared: set[str] = set()
    for document in changed_records:
        missing = REQUIRED_CHANGE_FIELDS - document.metadata.keys()
        if missing:
            errors.append(f"{relative(document.path)}: missing metadata {sorted(missing)}")
            continue
        errors.extend(validate_sections(document, REQUIRED_CHANGE_SECTIONS))
        if document.metadata["status"] != "unreleased":
            errors.append(f"{relative(document.path)}: status must be unreleased")
        for feature_id in document.metadata["features"]:
            declared.add(feature_id)
            if feature_id not in feature_by_id:
                errors.append(f"{relative(document.path)}: unknown Feature ID {feature_id}")
    if functional_paths and not changed_records:
        errors.append("Functional code changed without a new docs/changes/unreleased record")
    if functional_paths and not declared:
        errors.append("Functional code changed without any declared Feature ID")
    for feature_id in declared:
        document_path = feature_by_id.get(feature_id, {}).get("document")
        if document_path and document_path not in changed_feature_docs:
            errors.append(f"{feature_id}: current-state feature document was not updated in this change")
    covered_code = {
        code.rstrip("/")
        for feature_id in declared
        for code in feature_by_id.get(feature_id, {}).get("code", [])
    }
    for path in sorted(functional_paths):
        if path.startswith(("scripts/governance.py", "scripts/verify_change.ps1", ".github/", ".githooks/")):
            continue
        if not any(path == code or path.startswith(code + "/") for code in covered_code):
            errors.append(f"{path}: no declared Feature ID maps to this changed code path")
    if errors:
        raise GovernanceError("\n".join(errors))


def import_boundary_errors() -> list[str]:
    errors: list[str] = []
    source_root = ROOT / "src" / "kdesk"
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports_legacy = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports_legacy |= any(alias.name == "legacy" or alias.name.startswith("legacy.") for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports_legacy |= bool(node.module and (node.module == "legacy" or node.module.startswith("legacy.")))
        text = path.read_text(encoding="utf-8")
        loads_legacy_path = "spec_from_file_location" in text
        if (imports_legacy or loads_legacy_path) and path.name != "legacy_bridge.py":
            errors.append(f"{relative(path)}: only legacy_bridge.py may load legacy code")
    return errors


def validate_architecture() -> None:
    errors = import_boundary_errors()
    forbidden = ("order_send(", "positions_close(", "trade_transaction(", "balance_operation(")
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                errors.append(f"{relative(path)}: forbidden MT mutation token {token}")
    if errors:
        raise GovernanceError("\n".join(errors))


def openapi_payloads() -> dict[str, dict[str, Any]]:
    os.environ.setdefault("KDESK_PROFILE", "test")
    os.environ.setdefault("KDESK_RUNTIME_DIR", str(ROOT / "runtime" / "test" / "openapi"))
    sys.path.insert(0, str(ROOT / "src"))
    from kdesk.api.account_app import create_account_app
    from kdesk.api.kline_app import create_kline_app
    from kdesk.settings import Settings

    settings = Settings.load()
    return {"account.openapi.json": create_account_app(settings).openapi(), "kline.openapi.json": create_kline_app(settings).openapi()}


def validate_all(check_generated: bool, base: str | None) -> None:
    registry = build_registry()
    write_or_check(REGISTRY_PATH, registry, check_generated)
    for name, payload in openapi_payloads().items():
        write_or_check(OPENAPI_DIR / name, payload, check_generated)
    validate_changes(changed_paths(base), registry)
    validate_architecture()
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
    if package.get("version") != version:
        raise GovernanceError("frontend/package.json version does not match VERSION")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise GovernanceError("VERSION must be SemVer MAJOR.MINOR.PATCH")


def main() -> None:
    parser = argparse.ArgumentParser(description="K_desk feature governance")
    subparsers = parser.add_subparsers(dest="command", required=True)
    registry_parser = subparsers.add_parser("registry")
    registry_parser.add_argument("--check", action="store_true")
    openapi_parser = subparsers.add_parser("openapi")
    openapi_parser.add_argument("--check", action="store_true")
    validate_parser = subparsers.add_parser("validate")
    validate_parser.add_argument("--base", default="")
    validate_parser.add_argument("--write-generated", action="store_true")
    subparsers.add_parser("architecture")
    args = parser.parse_args()
    try:
        if args.command == "registry":
            write_or_check(REGISTRY_PATH, build_registry(), args.check)
        elif args.command == "openapi":
            for name, payload in openapi_payloads().items():
                write_or_check(OPENAPI_DIR / name, payload, args.check)
        elif args.command == "architecture":
            validate_architecture()
        else:
            validate_all(not args.write_generated, args.base or None)
    except GovernanceError as exc:
        print(f"GOVERNANCE ERROR\n{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps({"ok": True, "command": args.command, "at": datetime.now(UTC).isoformat()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
