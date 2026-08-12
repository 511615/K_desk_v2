from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, case, create_engine, event, func, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from kdesk.domain.ledger import DEFAULT_ACTIONS, LedgerRecord, now_text


class Base(DeclarativeBase):
    pass


class AccountRow(Base):
    __tablename__ = "accounts"

    record_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    account: Mapped[str] = mapped_column(String(64), index=True, default="")
    record_type: Mapped[str] = mapped_column(String(32), default="账户")
    related_subject: Mapped[str] = mapped_column(Text, default="")
    action: Mapped[str] = mapped_column(String(64), default="待定")
    current_group: Mapped[str] = mapped_column(String(128), default="")
    risk_tags: Mapped[str] = mapped_column(Text, default="")
    risk_note: Mapped[str] = mapped_column(Text, default="")
    raw_record: Mapped[str] = mapped_column(Text, default="")
    joined_at: Mapped[str] = mapped_column(String(32), default="")
    updated_at: Mapped[str] = mapped_column(String(32), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="待复核")
    owner_source: Mapped[str] = mapped_column(String(256), default="")
    ai_risk_level: Mapped[str] = mapped_column(String(64), default="")
    ai_note: Mapped[str] = mapped_column(Text, default="")
    ai_analysis_at: Mapped[str] = mapped_column(String(32), default="")
    ai_evidence_chart: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)


class HistoryRow(Base):
    __tablename__ = "account_history"

    history_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("accounts.record_id", ondelete="CASCADE"), index=True)
    account: Mapped[str] = mapped_column(String(64), default="")
    operation: Mapped[str] = mapped_column(String(32))
    changed_at: Mapped[str] = mapped_column(String(32), index=True)
    changed_fields_json: Mapped[str] = mapped_column(Text, default="[]")
    before_json: Mapped[str] = mapped_column(Text, default="{}")
    after_json: Mapped[str] = mapped_column(Text, default="{}")
    owner_source: Mapped[str] = mapped_column(String(256), default="")


class QuickActionRow(Base):
    __tablename__ = "quick_actions"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    protected: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginIpObservationRow(Base):
    __tablename__ = "login_ip_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account: Mapped[str] = mapped_column(String(64), index=True)
    platform: Mapped[str] = mapped_column(String(32), default="")
    server: Mapped[str] = mapped_column(String(128), default="")
    ip_address: Mapped[str] = mapped_column(String(64), index=True)
    first_seen_at: Mapped[str] = mapped_column(String(32))
    last_seen_at: Mapped[str] = mapped_column(String(32))
    geo_json: Mapped[str] = mapped_column(Text, default="{}")


class JobRunRow(Base):
    __tablename__ = "job_runs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str] = mapped_column(Text, default="{}")
    error: Mapped[str] = mapped_column(Text, default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=2)
    idempotency_key: Mapped[str] = mapped_column(String(256), index=True, default="")
    created_at: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[str] = mapped_column(String(32), default="")
    finished_at: Mapped[str] = mapped_column(String(32), default="")
    heartbeat_at: Mapped[str] = mapped_column(String(32), default="")
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)


class JobEventRow(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("job_runs.job_id", ondelete="CASCADE"), index=True)
    created_at: Mapped[str] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)


def _to_domain(row: AccountRow) -> LedgerRecord:
    return LedgerRecord(
        record_id=row.record_id,
        account=row.account,
        record_type=row.record_type,
        related_subject=row.related_subject,
        action=row.action,
        current_group=row.current_group,
        risk_tags=row.risk_tags,
        risk_note=row.risk_note,
        raw_record=row.raw_record,
        joined_at=row.joined_at,
        updated_at=row.updated_at,
        status=row.status,
        owner_source=row.owner_source,
        ai_risk_level=row.ai_risk_level,
        ai_note=row.ai_note,
        ai_analysis_at=row.ai_analysis_at,
        ai_evidence_chart=row.ai_evidence_chart,
        version=row.version,
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path.as_posix()}", future=True, connect_args={"timeout": 10})

        @event.listens_for(self.engine, "connect")
        def _configure_sqlite(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()

        self._session_factory = sessionmaker(self.engine, expire_on_commit=False, class_=Session)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self._session_factory() as session:
            with session.begin():
                yield session

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        with self.session() as session:
            if not session.scalar(select(QuickActionRow.name).limit(1)):
                session.add_all(
                    QuickActionRow(name=name, position=index, protected=name == "自定义")
                    for index, name in enumerate(DEFAULT_ACTIONS)
                )

    def count_accounts(self) -> int:
        with self._session_factory() as session:
            return len(session.scalars(select(AccountRow.record_id)).all())

    def list_accounts(self) -> list[LedgerRecord]:
        with self._session_factory() as session:
            rows = session.scalars(select(AccountRow).order_by(AccountRow.updated_at.desc(), AccountRow.account)).all()
            return [_to_domain(row) for row in rows]

    def get_account(self, record_id: str) -> LedgerRecord | None:
        with self._session_factory() as session:
            row = session.get(AccountRow, record_id)
            return _to_domain(row) if row else None

    def find_by_login(self, login: str) -> LedgerRecord | None:
        with self._session_factory() as session:
            row = session.scalar(select(AccountRow).where(AccountRow.account == str(login)).order_by(AccountRow.updated_at.desc()))
            return _to_domain(row) if row else None

    def actions_by_account(self, accounts: list[str] | set[str] | tuple[str, ...]) -> dict[str, str]:
        """Return the newest local ledger action for each requested account without scanning the ledger."""
        requested = sorted({str(account).strip() for account in accounts if str(account).strip()})
        actions: dict[str, str] = {}
        # SQLite has a conservative bound on variables; Kuzu result pages can contain up to 2,000 nodes.
        for offset in range(0, len(requested), 900):
            batch = requested[offset:offset + 900]
            with self._session_factory() as session:
                rows = session.execute(
                    select(AccountRow.account, AccountRow.action)
                    .where(AccountRow.account.in_(batch))
                    .order_by(AccountRow.account, AccountRow.updated_at.desc())
                ).all()
            for account, action in rows:
                actions.setdefault(str(account), str(action or ""))
        return actions

    def save_account(self, record: LedgerRecord, *, operation: str, before: dict | None = None) -> LedgerRecord:
        after = record.to_legacy()
        before = before or {}
        changed = [key for key, value in after.items() if before.get(key, "") != value]
        with self.session() as session:
            row = session.get(AccountRow, record.record_id) or AccountRow(record_id=record.record_id)
            for key in (
                "account", "record_type", "related_subject", "action", "current_group", "risk_tags", "risk_note",
                "raw_record", "joined_at", "updated_at", "status", "owner_source", "ai_risk_level", "ai_note",
                "ai_analysis_at", "ai_evidence_chart", "version",
            ):
                setattr(row, key, getattr(record, key))
            session.add(row)
            session.add(
                HistoryRow(
                    history_id=f"H-{uuid.uuid4().hex}",
                    record_id=record.record_id,
                    account=record.account,
                    operation=operation,
                    changed_at=record.updated_at,
                    changed_fields_json=json.dumps(changed, ensure_ascii=False),
                    before_json=json.dumps(before, ensure_ascii=False),
                    after_json=json.dumps(after, ensure_ascii=False),
                    owner_source=record.owner_source,
                )
            )
        return record

    def import_account(self, record: LedgerRecord) -> None:
        with self.session() as session:
            row = session.get(AccountRow, record.record_id) or AccountRow(record_id=record.record_id)
            for key in (
                "account", "record_type", "related_subject", "action", "current_group", "risk_tags", "risk_note",
                "raw_record", "joined_at", "updated_at", "status", "owner_source", "ai_risk_level", "ai_note",
                "ai_analysis_at", "ai_evidence_chart", "version",
            ):
                setattr(row, key, getattr(record, key))
            session.add(row)

    def import_history(self, payload: dict[str, str]) -> None:
        history_id = payload.get("历史ID") or f"H-{uuid.uuid4().hex}"
        record_id = payload.get("记录ID", "")
        if not record_id or not self.get_account(record_id):
            return
        with self.session() as session:
            if session.get(HistoryRow, history_id):
                return
            session.add(
                HistoryRow(
                    history_id=history_id,
                    record_id=record_id,
                    account=payload.get("账号", ""),
                    operation=payload.get("操作", "导入"),
                    changed_at=payload.get("修改时间", "") or now_text(),
                    changed_fields_json=payload.get("修改字段", "[]") or "[]",
                    before_json=payload.get("修改前JSON", "{}") or "{}",
                    after_json=payload.get("修改后JSON", "{}") or "{}",
                    owner_source=payload.get("处理人/来源", ""),
                )
            )

    def history(self, record_id: str) -> list[dict[str, str]]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(HistoryRow).where(HistoryRow.record_id == record_id).order_by(HistoryRow.changed_at.desc())
            ).all()
            return [
                {
                    "历史ID": row.history_id,
                    "记录ID": row.record_id,
                    "账号": row.account,
                    "操作": row.operation,
                    "修改时间": row.changed_at,
                    "修改字段": row.changed_fields_json,
                    "修改前JSON": row.before_json,
                    "修改后JSON": row.after_json,
                    "处理人/来源": row.owner_source,
                }
                for row in rows
            ]

    def delete_account(self, record_id: str) -> bool:
        with self.session() as session:
            row = session.get(AccountRow, record_id)
            if not row:
                return False
            session.delete(row)
            return True

    def quick_actions(self) -> list[str]:
        with self._session_factory() as session:
            return list(session.scalars(select(QuickActionRow.name).order_by(QuickActionRow.position, QuickActionRow.name)).all())

    def add_quick_action(self, name: str) -> list[str]:
        name = str(name or "").strip()
        if not name:
            raise ValueError("快捷标记不能为空")
        with self.session() as session:
            if not session.get(QuickActionRow, name):
                position = len(session.scalars(select(QuickActionRow.name)).all())
                session.add(QuickActionRow(name=name, position=position, protected=name == "自定义"))
        return self.quick_actions()

    def delete_quick_action(self, name: str) -> list[str]:
        with self.session() as session:
            row = session.get(QuickActionRow, name)
            if row and not row.protected:
                session.delete(row)
        return self.quick_actions()

    def create_job(self, kind: str, payload: dict, *, idempotency_key: str = "", max_attempts: int = 2) -> dict:
        with self.session() as session:
            if idempotency_key:
                existing = session.scalar(
                    select(JobRunRow).where(
                        JobRunRow.idempotency_key == idempotency_key,
                        JobRunRow.status.in_(["queued", "running"]),
                    ).order_by(JobRunRow.created_at.desc())
                )
                if existing:
                    return self._job_dict(existing)
            row = JobRunRow(
                job_id=uuid.uuid4().hex,
                kind=kind,
                status="queued",
                payload_json=json.dumps(payload, ensure_ascii=False),
                result_json="{}",
                error="",
                progress=0,
                attempts=0,
                max_attempts=max_attempts,
                idempotency_key=idempotency_key,
                created_at=now_text(),
                started_at="",
                finished_at="",
                heartbeat_at="",
                cancel_requested=False,
            )
            session.add(row)
            session.flush()
            return self._job_dict(row)

    @staticmethod
    def _job_dict(row: JobRunRow) -> dict:
        try:
            payload = json.loads(row.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        try:
            result = json.loads(row.result_json or "{}")
        except json.JSONDecodeError:
            result = {}
        return {
            "id": row.job_id,
            "kind": row.kind,
            "status": row.status,
            "payload": payload,
            "result": result,
            "error": row.error,
            "progress": row.progress,
            "attempts": row.attempts,
            "max_attempts": row.max_attempts,
            "created_at": row.created_at,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "heartbeat_at": row.heartbeat_at,
            "cancel_requested": row.cancel_requested,
        }

    def get_job(self, job_id: str) -> dict | None:
        with self._session_factory() as session:
            row = session.get(JobRunRow, job_id)
            if not row:
                return None
            payload = self._job_dict(row)
            payload["events"] = [
                {"at": event.created_at, "level": event.level, "message": event.message}
                for event in session.scalars(
                    select(JobEventRow).where(JobEventRow.job_id == job_id).order_by(JobEventRow.id)
                ).all()
            ]
            return payload

    def get_active_job(self, kind: str) -> dict | None:
        with self._session_factory() as session:
            row = session.scalar(
                select(JobRunRow)
                .where(JobRunRow.kind == kind, JobRunRow.status.in_(["queued", "running"]))
                .order_by(
                    case((JobRunRow.status == "running", 0), else_=1),
                    JobRunRow.started_at.desc(),
                    JobRunRow.created_at.desc(),
                )
            )
            return self._job_dict(row) if row else None

    def claim_next_job(self, *, kinds: tuple[str, ...] | None = None) -> dict | None:
        if kinds is not None and not kinds:
            return None
        # Select and claim in one write transaction. Multiple discovery Workers may
        # poll concurrently; the conditional update ensures only one can win.
        now = now_text()
        with self.engine.begin() as connection:
            statement = select(JobRunRow.job_id).where(JobRunRow.status == "queued")
            if kinds is not None:
                statement = statement.where(JobRunRow.kind.in_(kinds))
            job_id = connection.execute(statement.order_by(JobRunRow.created_at).limit(1)).scalar_one_or_none()
            if not job_id:
                return None
            claimed = connection.execute(
                update(JobRunRow)
                .where(JobRunRow.job_id == job_id, JobRunRow.status == "queued")
                .values(
                    status="running",
                    started_at=func.coalesce(JobRunRow.started_at, now),
                    heartbeat_at=now,
                    attempts=JobRunRow.attempts + 1,
                )
            )
            if claimed.rowcount != 1:
                return None
        with self._session_factory() as session:
            row = session.get(JobRunRow, job_id)
            return self._job_dict(row) if row else None

    def update_job(self, job_id: str, *, status: str | None = None, progress: int | None = None, result: dict | None = None, error: str | None = None, event_message: str = "", event_level: str = "info") -> None:
        with self.session() as session:
            row = session.get(JobRunRow, job_id)
            if not row:
                return
            if status is not None:
                row.status = status
                if status in {"done", "failed", "cancelled"}:
                    row.finished_at = now_text()
            if progress is not None:
                row.progress = max(0, min(100, int(progress)))
            if result is not None:
                row.result_json = json.dumps(result, ensure_ascii=False)
            if error is not None:
                row.error = error
            row.heartbeat_at = now_text()
            if event_message:
                session.add(JobEventRow(job_id=job_id, created_at=now_text(), level=event_level, message=event_message[-8000:]))

    def touch_job(self, job_id: str) -> None:
        """Refresh a running job lease without adding a visible progress event."""
        with self.session() as session:
            row = session.get(JobRunRow, job_id)
            if row and row.status == "running":
                row.heartbeat_at = now_text()

    def request_job_cancel(self, job_id: str) -> dict | None:
        with self.session() as session:
            row = session.get(JobRunRow, job_id)
            if not row:
                return None
            row.cancel_requested = True
            if row.status == "queued":
                row.status = "cancelled"
                row.finished_at = now_text()
                session.add(JobEventRow(job_id=job_id, created_at=now_text(), level="info", message="任务在执行前取消"))
            session.flush()
            return self._job_dict(row)

    def recover_interrupted_jobs(
        self,
        *,
        kinds: tuple[str, ...] | None = None,
        stale_after_seconds: int = 0,
    ) -> int:
        if kinds is not None and not kinds:
            return 0
        if stale_after_seconds < 0:
            raise ValueError("stale_after_seconds must be non-negative")
        recovered = 0
        now = datetime.now()
        with self.session() as session:
            statement = select(JobRunRow).where(JobRunRow.status == "running")
            if kinds is not None:
                statement = statement.where(JobRunRow.kind.in_(kinds))
            rows = session.scalars(statement).all()
            for row in rows:
                if stale_after_seconds:
                    heartbeat_text = row.heartbeat_at or row.started_at or row.created_at
                    try:
                        heartbeat = datetime.strptime(heartbeat_text, "%Y-%m-%d %H:%M:%S")
                    except (TypeError, ValueError):
                        heartbeat = datetime.min
                    if now - heartbeat < timedelta(seconds=stale_after_seconds):
                        continue
                if row.cancel_requested:
                    row.status = "cancelled"
                    row.finished_at = now_text()
                elif row.attempts < row.max_attempts:
                    row.status = "queued"
                    row.error = "Worker restarted before completion"
                else:
                    row.status = "failed"
                    row.finished_at = now_text()
                    row.error = "Worker interrupted after maximum attempts"
                message = "Worker租约超时，任务状态已恢复" if stale_after_seconds else "Worker重启，任务状态已恢复"
                session.add(JobEventRow(job_id=row.job_id, created_at=now_text(), level="warning", message=message))
                recovered += 1
        return recovered
