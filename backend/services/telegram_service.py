"""
services/telegram_service.py — Fire Sentinel

Uses the Telegram Bot HTTP API directly (no extra SDK dependency). Two send
paths: plain text, and photo-with-caption for snapshot-backed alerts.
"""

import requests
import config

TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"


def _api_url(method):
    return TELEGRAM_API_BASE.format(token=config.TELEGRAM_BOT_TOKEN, method=method)


def send_text(message: str, chat_id: str | None = None) -> tuple[bool, str]:
    """Sends a plain text message. Returns (success, error_detail)."""
    if not config.TELEGRAM_ENABLED:
        return False, "Telegram not configured (missing bot token or chat id)"

    try:
        resp = requests.post(
            _api_url("sendMessage"),
            data={"chat_id": chat_id or config.TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"},
            timeout=10,
        )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, ""
        return False, f"Telegram API returned {resp.status_code}: {resp.text}"
    except requests.RequestException as e:
        return False, f"Telegram request failed: {e}"


def send_photo(caption: str, photo_path: str, chat_id: str | None = None) -> tuple[bool, str]:
    """Sends a photo with a caption — used for CONFIRMING/FIRE_CONFIRMED alerts
    where a snapshot exists. Falls back to text-only if the file is missing.
    """
    if not config.TELEGRAM_ENABLED:
        return False, "Telegram not configured (missing bot token or chat id)"

    try:
        with open(photo_path, "rb") as photo_file:
            resp = requests.post(
                _api_url("sendPhoto"),
                data={"chat_id": chat_id or config.TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": photo_file},
                timeout=20,
            )
        if resp.status_code == 200 and resp.json().get("ok"):
            return True, ""
        return False, f"Telegram API returned {resp.status_code}: {resp.text}"
    except FileNotFoundError:
        return send_text(caption + "\n(snapshot file not found, sent as text-only)", chat_id=chat_id)
    except requests.RequestException as e:
        return False, f"Telegram photo request failed: {e}"
