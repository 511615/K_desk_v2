from __future__ import annotations

from collections import Counter
from pathlib import Path

from kdesk.domain.ledger import DEFAULT_STATUSES, LedgerRecord
from kdesk.infrastructure.database import Database
from kdesk.infrastructure.excel_io import export_workbook, import_workbook, preview_import


class LedgerService:
    def __init__(self, database: Database, *, compatibility_workbook: Path | None = None):
        self.database = database
        self.compatibility_workbook = compatibility_workbook

    def _mirror(self) -> None:
        if self.compatibility_workbook:
            export_workbook(self.compatibility_workbook, self.database)

    def summary(self, records: list[LedgerRecord] | None = None) -> dict:
        records = records if records is not None else self.database.list_accounts()
        statuses = Counter(record.status for record in records)
        actions = Counter(record.action for record in records)
        return {"total": len(records), "statuses": dict(statuses), "actions": dict(actions)}

    def list_payload(self) -> dict:
        records = self.database.list_accounts()
        return {
            "ok": True,
            "summary": self.summary(records),
            "records": [record.to_legacy() for record in records],
            "statuses": DEFAULT_STATUSES,
            "actions": self.database.quick_actions(),
        }

    def ledger_for_login(self, login: str) -> dict:
        record = self.database.find_by_login(login)
        return {
            "ok": True,
            "account": str(login),
            "marked": bool(record),
            "record": record.to_legacy() if record else None,
            "actions": self.database.quick_actions(),
            "statuses": DEFAULT_STATUSES,
        }

    def save(self, payload: dict, record_id: str | None = None) -> dict:
        existing = self.database.get_account(record_id) if record_id else None
        if record_id and existing is None:
            payload = {**payload, "记录ID": record_id}
        record = LedgerRecord.from_mapping(payload, existing)
        operation = "修改" if existing else "新增"
        saved = self.database.save_account(record, operation=operation, before=existing.to_legacy() if existing else {})
        self._mirror()
        return {"ok": True, "record": saved.to_legacy(), "summary": self.summary()}

    def save_many(self, payload: dict, accounts: list[object]) -> dict:
        saved = []
        for account in accounts:
            login = str(account or "").strip()
            if not login:
                continue
            existing = self.database.find_by_login(login)
            item = {**payload, "账号": login}
            saved.append(self.save(item, existing.record_id if existing else None)["record"])
        return {"ok": True, "records": saved, "summary": self.summary()}

    def delete(self, record_id: str) -> dict:
        deleted = self.database.delete_account(record_id)
        if deleted:
            self._mirror()
        return {"ok": deleted, "summary": self.summary()}

    def import_preview(self, path: Path) -> dict:
        return {"ok": True, **preview_import(path, self.database)}

    def import_excel(self, path: Path, *, allow_conflicts: bool = False) -> dict:
        result = import_workbook(path, self.database, allow_conflicts=allow_conflicts)
        self._mirror()
        return {"ok": True, **result}

    def export_excel(self, path: Path) -> Path:
        return export_workbook(path, self.database)
