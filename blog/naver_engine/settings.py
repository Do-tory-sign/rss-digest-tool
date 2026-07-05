from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import CREDENTIAL_PREFIX, DATA_DIR, read_json, write_json


SETTINGS_PATH = DATA_DIR / "dotory_blofit_settings.json"


@dataclass
class IlluaSettings:
    naver_id: str = ""
    naver_login_id: str = ""
    auto_login_enabled: bool = False
    telegram_enabled: bool = False
    telegram_chat_id: str = ""
    editor_x: int = 0
    editor_y: int = 0
    save_button_x: int = 0
    save_button_y: int = 0
    publish_button1_x: int = 0
    publish_button1_y: int = 0
    publish_button2_x: int = 0
    publish_button2_y: int = 0
    publish_click_delay_seconds: int = 5
    auto_publish_enabled: bool = False
    auto_wait_seconds: int = 8

    @property
    def ready(self) -> bool:
        return bool(self.naver_id.strip())

    @property
    def publish_ready(self) -> bool:
        return (
            self.publish_button1_x > 0
            and self.publish_button1_y > 0
            and self.publish_button2_x > 0
            and self.publish_button2_y > 0
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "naver_id": self.naver_id.strip(),
            "naver_login_id": self.naver_login_id.strip(),
            "auto_login_enabled": bool(self.auto_login_enabled),
            "telegram_enabled": bool(self.telegram_enabled),
            "telegram_chat_id": self.telegram_chat_id.strip(),
            "editor_x": int(self.editor_x),
            "editor_y": int(self.editor_y),
            "save_button_x": int(self.save_button_x),
            "save_button_y": int(self.save_button_y),
            "publish_button1_x": int(self.publish_button1_x),
            "publish_button1_y": int(self.publish_button1_y),
            "publish_button2_x": int(self.publish_button2_x),
            "publish_button2_y": int(self.publish_button2_y),
            "publish_click_delay_seconds": int(self.publish_click_delay_seconds),
            "auto_publish_enabled": bool(self.auto_publish_enabled),
            "auto_wait_seconds": int(self.auto_wait_seconds),
        }


def load_illua_settings() -> IlluaSettings:
    payload = read_json(SETTINGS_PATH, {})
    if not isinstance(payload, dict):
        payload = {}
    return IlluaSettings(
        naver_id=str(payload.get("naver_id") or ""),
        naver_login_id=str(payload.get("naver_login_id") or ""),
        auto_login_enabled=bool(payload.get("auto_login_enabled") or False),
        telegram_enabled=bool(payload.get("telegram_enabled") or False),
        telegram_chat_id=str(payload.get("telegram_chat_id") or ""),
        editor_x=int(payload.get("editor_x") or 0),
        editor_y=int(payload.get("editor_y") or 0),
        save_button_x=int(payload.get("save_button_x") or 0),
        save_button_y=int(payload.get("save_button_y") or 0),
        publish_button1_x=int(payload.get("publish_button1_x") or 0),
        publish_button1_y=int(payload.get("publish_button1_y") or 0),
        publish_button2_x=int(payload.get("publish_button2_x") or 0),
        publish_button2_y=int(payload.get("publish_button2_y") or 0),
        publish_click_delay_seconds=int(payload.get("publish_click_delay_seconds") or 5),
        auto_publish_enabled=bool(payload.get("auto_publish_enabled") or False),
        auto_wait_seconds=int(payload.get("auto_wait_seconds") or 8),
    )


def save_illua_settings(settings: IlluaSettings) -> Path:
    write_json(SETTINGS_PATH, settings.as_dict())
    return SETTINGS_PATH


def credential_login_id(settings: IlluaSettings) -> str:
    return (settings.naver_login_id or settings.naver_id).strip()


def credential_target(login_id: str) -> str:
    return f"{CREDENTIAL_PREFIX}:Naver:{login_id.strip()}"


def telegram_credential_target() -> str:
    return f"{CREDENTIAL_PREFIX}:TelegramBotToken"


def save_naver_password(login_id: str, password: str) -> bool:
    if not login_id.strip() or not password:
        return False
    try:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": credential_target(login_id),
                "UserName": login_id.strip(),
                "CredentialBlob": password,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )
        return True
    except Exception:
        return False


def load_naver_password(login_id: str) -> str:
    if not login_id.strip():
        return ""
    try:
        import win32cred

        credential = win32cred.CredRead(credential_target(login_id), win32cred.CRED_TYPE_GENERIC)
        blob = credential.get("CredentialBlob") or b""
        if isinstance(blob, bytes):
            return blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
        return str(blob)
    except Exception:
        return ""


def delete_naver_password(login_id: str) -> bool:
    if not login_id.strip():
        return False
    try:
        import win32cred

        win32cred.CredDelete(credential_target(login_id), win32cred.CRED_TYPE_GENERIC)
        return True
    except Exception:
        return False


def save_telegram_bot_token(token: str) -> bool:
    if not token.strip():
        return False
    try:
        import win32cred

        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": telegram_credential_target(),
                "UserName": "telegram_bot_token",
                "CredentialBlob": token.strip(),
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )
        return True
    except Exception:
        return False


def load_telegram_bot_token() -> str:
    try:
        import win32cred

        credential = win32cred.CredRead(telegram_credential_target(), win32cred.CRED_TYPE_GENERIC)
        blob = credential.get("CredentialBlob") or b""
        if isinstance(blob, bytes):
            return blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
        return str(blob)
    except Exception:
        return ""


def delete_telegram_bot_token() -> bool:
    try:
        import win32cred

        win32cred.CredDelete(telegram_credential_target(), win32cred.CRED_TYPE_GENERIC)
        return True
    except Exception:
        return False
