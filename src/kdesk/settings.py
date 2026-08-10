from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name, "").strip()
    return Path(value) if value else default


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name, "").strip()
    return int(value) if value else default


@dataclass(frozen=True, slots=True)
class Settings:
    root: Path
    profile: str
    host: str
    account_port: int
    kline_port: int
    runtime_dir: Path
    database_path: Path
    queue_database_path: Path
    artifact_dir: Path
    upload_dir: Path
    log_dir: Path
    legacy_root: Path
    legacy_output: Path
    legacy_trade_database: Path
    bootstrap_xlsx: Path
    legacy_compat_dir: Path
    frontend_dist: Path
    ui_mode: str
    copy_pool_output_dir: Path | None = None
    kuzu_demo_path: Path | None = None
    kuzu_risk_path: Path | None = None

    @classmethod
    def load(cls) -> Settings:
        inferred_root = Path(__file__).resolve().parents[2]
        root = _env_path("KDESK_V2_ROOT", inferred_root).resolve()
        profile = os.environ.get("KDESK_PROFILE", "dev").strip().lower() or "dev"
        default_runtime = root / "runtime" / profile
        runtime_dir = _env_path("KDESK_RUNTIME_DIR", default_runtime).resolve()
        legacy_output = _env_path("KDESK_LEGACY_OUTPUT", Path(r"D:\risk\output_data")).resolve()
        return cls(
            root=root,
            profile=profile,
            host=os.environ.get("KDESK_HOST", "127.0.0.1"),
            account_port=_env_int("KDESK_ACCOUNT_PORT", 8877 if profile != "prod" else 8777),
            kline_port=_env_int("KDESK_KLINE_PORT", 8866 if profile != "prod" else 8766),
            runtime_dir=runtime_dir,
            database_path=_env_path("KDESK_DATABASE", runtime_dir / "kdesk.sqlite").resolve(),
            queue_database_path=_env_path("KDESK_QUEUE_DATABASE", runtime_dir / "jobs.sqlite").resolve(),
            artifact_dir=_env_path("KDESK_ARTIFACT_DIR", runtime_dir / "artifacts").resolve(),
            upload_dir=_env_path("KDESK_UPLOAD_DIR", runtime_dir / "uploads").resolve(),
            log_dir=_env_path("KDESK_LOG_DIR", runtime_dir / "logs").resolve(),
            legacy_root=(root / "legacy").resolve(),
            legacy_output=legacy_output,
            legacy_trade_database=_env_path(
                "KDESK_LEGACY_TRADE_DATABASE", legacy_output / "account_trade_lookup" / "trades.sqlite"
            ).resolve(),
            bootstrap_xlsx=_env_path("KDESK_BOOTSTRAP_XLSX", runtime_dir / "import" / "problematic_accounts.xlsx").resolve(),
            legacy_compat_dir=(runtime_dir / "legacy_compat").resolve(),
            frontend_dist=_env_path("KDESK_FRONTEND_DIST", root / "frontend" / "dist").resolve(),
            ui_mode=os.environ.get("KDESK_UI_MODE", "vue").strip().lower() or "vue",
            copy_pool_output_dir=_env_path(
                "KDESK_COPY_POOL_OUTPUT_DIR",
                legacy_output / "copy_live_demo_capital10k",
            ).resolve(),
            kuzu_demo_path=_env_path(
                "KDESK_KUZU_DEMO_DB",
                runtime_dir / "relationship_graph_demo.kuzu",
            ).resolve(),
            kuzu_risk_path=_env_path(
                "KDESK_KUZU_RISK_DB",
                runtime_dir / "relationship_risk_graph.kuzu",
            ).resolve(),
        )

    def ensure_runtime(self) -> None:
        for path in (
            self.runtime_dir,
            self.database_path.parent,
            self.queue_database_path.parent,
            self.artifact_dir,
            self.upload_dir,
            self.log_dir,
            self.bootstrap_xlsx.parent,
            self.legacy_compat_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


settings = Settings.load()
