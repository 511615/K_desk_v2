from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

LEGACY_HEADERS = [
    "记录ID",
    "账号",
    "记录类型",
    "关联账号/主体",
    "建议动作",
    "当前分组",
    "风险标签",
    "风险/问题备注",
    "原始记录",
    "加入时间",
    "修改时间",
    "状态",
    "处理人/来源",
    "AI风险等级",
    "AI备注",
    "AI分析时间",
    "AI证据图表",
]

LEGACY_HISTORY_HEADERS = [
    "历史ID",
    "记录ID",
    "账号",
    "操作",
    "修改时间",
    "修改字段",
    "修改前JSON",
    "修改后JSON",
    "处理人/来源",
]

DEFAULT_ACTIONS = ["B", "M", "M观察", "P", "P观察", "T", "A", "A/TA", "B-M", "B-P", "M-P", "P->A/T", "限制出金", "自定义", "待定"]
DEFAULT_STATUSES = ["待复核", "观察中", "已确认", "已关闭"]


def clean(value: object) -> str:
    return str(value or "").strip()


def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def stable_record_id(account: str, seed: str = "") -> str:
    account = clean(account)
    if account and re.fullmatch(r"[0-9A-Za-z_-]+", account):
        return f"ACC-{account}"
    digest = hashlib.sha1((account or seed).encode("utf-8")).hexdigest()[:12]
    return f"ACC-TEXT-{digest}" if account else f"REC-{digest}"


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    record_id: str
    account: str
    record_type: str
    related_subject: str
    action: str
    current_group: str
    risk_tags: str
    risk_note: str
    raw_record: str
    joined_at: str
    updated_at: str
    status: str
    owner_source: str
    ai_risk_level: str = ""
    ai_note: str = ""
    ai_analysis_at: str = ""
    ai_evidence_chart: str = ""
    version: int = 1

    @classmethod
    def from_mapping(cls, source: Mapping[str, object], existing: LedgerRecord | None = None) -> LedgerRecord:
        def pick(legacy: str, english: str, default: str = "") -> str:
            if legacy in source:
                return clean(source.get(legacy))
            if english in source:
                return clean(source.get(english))
            return clean(getattr(existing, english, default) if existing else default)

        account = pick("账号", "account")
        source_updated_at = pick("修改时间", "updated_at")
        updated_at = source_updated_at if existing is None and source_updated_at else now_text()
        joined_at = pick("加入时间", "joined_at", updated_at) or updated_at
        record_id = pick("记录ID", "record_id") or (existing.record_id if existing else stable_record_id(account, updated_at))
        return cls(
            record_id=record_id,
            account=account,
            record_type=pick("记录类型", "record_type", "账户" if account else "其他") or ("账户" if account else "其他"),
            related_subject=pick("关联账号/主体", "related_subject"),
            action=pick("建议动作", "action", "待定") or "待定",
            current_group=pick("当前分组", "current_group"),
            risk_tags=pick("风险标签", "risk_tags"),
            risk_note=pick("风险/问题备注", "risk_note"),
            raw_record=pick("原始记录", "raw_record"),
            joined_at=joined_at,
            updated_at=updated_at,
            status=pick("状态", "status", "待复核") or "待复核",
            owner_source=pick("处理人/来源", "owner_source"),
            ai_risk_level=pick("AI风险等级", "ai_risk_level"),
            ai_note=pick("AI备注", "ai_note"),
            ai_analysis_at=pick("AI分析时间", "ai_analysis_at"),
            ai_evidence_chart=pick("AI证据图表", "ai_evidence_chart"),
            version=(existing.version + 1) if existing else 1,
        )

    def to_legacy(self) -> dict[str, str]:
        return {
            "记录ID": self.record_id,
            "账号": self.account,
            "记录类型": self.record_type,
            "关联账号/主体": self.related_subject,
            "建议动作": self.action,
            "当前分组": self.current_group,
            "风险标签": self.risk_tags,
            "风险/问题备注": self.risk_note,
            "原始记录": self.raw_record,
            "加入时间": self.joined_at,
            "修改时间": self.updated_at,
            "状态": self.status,
            "处理人/来源": self.owner_source,
            "AI风险等级": self.ai_risk_level,
            "AI备注": self.ai_note,
            "AI分析时间": self.ai_analysis_at,
            "AI证据图表": self.ai_evidence_chart,
        }
