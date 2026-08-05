from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    # A packaged seller build must never read credentials from beside the EXE.
    # .env is supported only while running from source for development/testing.
    if getattr(sys, "frozen", False) and path is None:
        return values
    env_path = path or project_root() / ".env"
    if not env_path.exists():
        return values
    for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://hipersonalization.com"
    seller_username: str = ""
    seller_password: str = ""

    @classmethod
    def from_environment(cls) -> "Settings":
        file_values = load_env()

        def value(name: str, default: str = "") -> str:
            return os.getenv(name, file_values.get(name, default))

        return cls(
            base_url=value("HIPERSONALIZATION_BASE_URL", cls.base_url).rstrip("/"),
            seller_username=value("HIPERSONALIZATION_SELLER_USERNAME"),
            seller_password=value("HIPERSONALIZATION_SELLER_PASSWORD"),
        )


def app_data_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.getenv("LOCALAPPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.getenv("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    target = root / "HiPersonalizationAssistant"
    target.mkdir(parents=True, exist_ok=True)
    return target
