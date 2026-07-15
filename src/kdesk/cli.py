from __future__ import annotations

import argparse
import json
from pathlib import Path

from kdesk.application.ledger_service import LedgerService
from kdesk.infrastructure.database import Database
from kdesk.infrastructure.excel_io import export_audit_json
from kdesk.settings import settings


def _service() -> LedgerService:
    settings.ensure_runtime()
    database = Database(settings.database_path)
    database.create_schema()
    return LedgerService(database, compatibility_workbook=settings.legacy_compat_dir / "problematic_accounts.xlsx")


def main() -> None:
    parser = argparse.ArgumentParser(prog="kdesk")
    sub = parser.add_subparsers(dest="command", required=True)
    preview = sub.add_parser("import-preview")
    preview.add_argument("xlsx")
    apply_import = sub.add_parser("import-excel")
    apply_import.add_argument("xlsx")
    apply_import.add_argument("--allow-conflicts", action="store_true")
    export = sub.add_parser("export-excel")
    export.add_argument("xlsx")
    args = parser.parse_args()

    service = _service()
    if args.command == "import-preview":
        result = service.import_preview(Path(args.xlsx))
    elif args.command == "import-excel":
        result = service.import_excel(Path(args.xlsx), allow_conflicts=args.allow_conflicts)
        export_audit_json(settings.runtime_dir / "import" / "last_import.json", result)
    else:
        path = service.export_excel(Path(args.xlsx))
        result = {"ok": True, "path": str(path)}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
