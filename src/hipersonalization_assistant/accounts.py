from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import keyring
from keyring.errors import KeyringError, PasswordDeleteError


class CredentialStoreError(RuntimeError):
    pass


class AccountStore:
    """Store account names in JSON and passwords in the operating-system credential vault."""

    SERVICE_NAME = "HiPersonalizationAssistant"

    def __init__(self, metadata_path: Path, backend: Any = keyring):
        self.metadata_path = metadata_path
        self.backend = backend
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, Any]:
        if not self.metadata_path.exists():
            return {"accounts": [], "last_account": ""}
        try:
            value = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"accounts": [], "last_account": ""}
        accounts = value.get("accounts", [])
        if not isinstance(accounts, list):
            accounts = []
        return {
            "accounts": [str(item) for item in accounts if str(item).strip()],
            "last_account": str(value.get("last_account", "")),
        }

    def _write(self, value: dict[str, Any]) -> None:
        temporary = self.metadata_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.metadata_path)

    def accounts(self) -> list[str]:
        return self._read()["accounts"]

    def last_account(self) -> str:
        value = self._read()
        last = value["last_account"]
        return last if last in value["accounts"] else ""

    def password(self, username: str) -> str | None:
        try:
            return self.backend.get_password(self.SERVICE_NAME, username)
        except KeyringError as exc:
            raise CredentialStoreError(f"无法读取系统凭据库：{exc}") from exc

    def save(self, username: str, password: str) -> None:
        username = username.strip()
        if not username or not password:
            raise CredentialStoreError("账号和密码不能为空。")
        try:
            self.backend.set_password(self.SERVICE_NAME, username, password)
        except KeyringError as exc:
            raise CredentialStoreError(f"无法写入系统凭据库：{exc}") from exc
        value = self._read()
        if username not in value["accounts"]:
            value["accounts"].append(username)
        value["last_account"] = username
        self._write(value)

    def set_last_account(self, username: str) -> None:
        value = self._read()
        if username in value["accounts"]:
            value["last_account"] = username
            self._write(value)

    def forget_password(self, username: str) -> None:
        try:
            self.backend.delete_password(self.SERVICE_NAME, username)
        except PasswordDeleteError:
            pass
        except KeyringError as exc:
            raise CredentialStoreError(f"无法更新系统凭据库：{exc}") from exc

    def remove(self, username: str) -> None:
        self.forget_password(username)
        value = self._read()
        value["accounts"] = [item for item in value["accounts"] if item != username]
        if value["last_account"] == username:
            value["last_account"] = value["accounts"][0] if value["accounts"] else ""
        self._write(value)
