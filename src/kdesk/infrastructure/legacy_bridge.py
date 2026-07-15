from __future__ import annotations

import importlib.util
import os
import sys
import threading
from collections.abc import Callable
from types import ModuleType
from typing import Any

from kdesk.settings import Settings


class LegacyBridge:
    """Compatibility boundary around the current production implementation.

    This adapter is deliberately the only v2 module allowed to import the legacy
    monolith. It is replaced one use case at a time while API parity is retained.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self._module: ModuleType | None = None
        self._lock = threading.Lock()

    def _configure_environment(self) -> None:
        compat = self.settings.legacy_compat_dir
        compat.mkdir(parents=True, exist_ok=True)
        os.environ["K_DESK_ROOT"] = str(self.settings.root)
        os.environ["ACCOUNT_REGISTRY_DATA_DIR"] = str(compat)
        os.environ["ACCOUNT_QUICK_ACTIONS_PATH"] = str(compat / "quick_actions.json")
        os.environ["ACCOUNT_LOGIN_IP_DB_PATH"] = str(self.settings.runtime_dir / "account_login_ips.sqlite")
        os.environ["ACCOUNT_TRADE_DB_PATH"] = str(self.settings.legacy_trade_database)
        os.environ["TRADE_KLINE_OUT_DIR"] = str(self.settings.artifact_dir)
        os.environ["TRADE_KLINE_TOOL_DIR"] = str(self.settings.legacy_root / "tools" / "trade_kline_tool")
        os.environ["TRADE_KLINE_WEB_URL"] = f"http://{self.settings.host}:{self.settings.kline_port}"
        os.environ.setdefault("TRADE_KLINE_PYDEPS", r"D:\risk\pydeps")
        os.environ.setdefault("K_DESK_PYTHON", sys.executable)

    def module(self) -> ModuleType:
        if self._module is not None:
            return self._module
        with self._lock:
            if self._module is not None:
                return self._module
            self._configure_environment()
            app_dir = self.settings.legacy_root / "apps" / "problem_account_registry"
            app_path = app_dir / "app.py"
            if not app_path.exists():
                raise RuntimeError(f"Legacy account application is missing: {app_path}")
            if str(app_dir) not in sys.path:
                sys.path.insert(0, str(app_dir))
            spec = importlib.util.spec_from_file_location("kdesk_v2_legacy_account_app", app_path)
            if spec is None or spec.loader is None:
                raise RuntimeError(f"Cannot load legacy account application: {app_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            self._module = module
            return module

    def function(self, name: str) -> Callable[..., Any]:
        function = getattr(self.module(), name, None)
        if not callable(function):
            raise RuntimeError(f"Legacy compatibility function is unavailable: {name}")
        return function

    def call(self, name: str, *args, **kwargs):
        return self.function(name)(*args, **kwargs)

    def account_page(self, login: str) -> str:
        module = self.module()
        import json

        page = module.ACCOUNT_DETAIL_HTML.replace("__ACCOUNT_LOGIN_JSON__", json.dumps(login, ensure_ascii=False))
        return page.replace("http://127.0.0.1:8766", f"http://{self.settings.host}:{self.settings.kline_port}")

    def workbench_page(self) -> str:
        page = self.module().WORKBENCH_HTML
        return page.replace("http://127.0.0.1:8766", f"http://{self.settings.host}:{self.settings.kline_port}")
