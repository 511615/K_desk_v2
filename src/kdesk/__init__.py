"""K_desk modular application package."""

from pathlib import Path


def _read_version() -> str:
    version_path = Path(__file__).resolve().parents[2] / "VERSION"
    return version_path.read_text(encoding="utf-8").strip()


__version__ = _read_version()
