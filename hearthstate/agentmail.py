from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


API_BASE = "https://api.agentmail.to/v0"
DEFAULT_SECRET_DIR = Path("/home/ubuntu/.hermes/secret")
DEFAULT_PUBLIC_URL = "http://vnic.tail015325.ts.net:8788"


def _secret_dir(secret_dir: Path | str | None = None) -> Path:
    return Path(secret_dir or os.environ.get("HEARTHSTATE_AGENTMAIL_SECRET_DIR", DEFAULT_SECRET_DIR)).expanduser()


def _public_url(public_url: str | None = None) -> str:
    return (public_url or os.environ.get("HEARTHSTATE_PUBLIC_URL", DEFAULT_PUBLIC_URL)).rstrip("/")


def _read_secret(secret_dir: Path, name: str) -> str:
    value = (secret_dir / name).read_text(encoding="utf-8").strip()
    if not value:
        raise ValueError(f"AgentMail secret is empty: {name}")
    return value


def build_message(delivery: dict[str, str], *, kind: str, public_url: str | None = None) -> dict[str, str]:
    recipient = str(delivery.get("email", "")).strip()
    relative_url = str(delivery.get("url", "")).strip()
    if not recipient or not relative_url.startswith("/"):
        raise ValueError("invalid AgentMail delivery metadata")
    link = f"{_public_url(public_url)}{relative_url}"
    if kind == "invitation":
        subject = "You have been invited to Hearthstate"
        text = (
            "You have been invited to join a household on Hearthstate.\n\n"
            f"Open this invitation to join: {link}\n\n"
            "This invitation is single-use and expires soon."
        )
    elif kind == "sign_in":
        subject = "Your Hearthstate sign-in link"
        text = (
            "Use this one-time link to sign in to Hearthstate:\n\n"
            f"{link}\n\n"
            "If you did not request this, you can ignore this email."
        )
    else:
        raise ValueError("unsupported AgentMail delivery kind")
    return {"to": recipient, "subject": subject, "text": text}


def send_message(
    message: dict[str, str],
    *,
    secret_dir: Path | str | None = None,
) -> dict:
    secrets_dir = _secret_dir(secret_dir)
    api_key = _read_secret(secrets_dir, "agentmail_api_key")
    inbox_id = _read_secret(secrets_dir, "agentmail_inbox_id")
    payload = {
        "to": message["to"],
        "subject": message["subject"],
        "text": message["text"],
    }
    request = Request(
        f"{API_BASE}/inboxes/{quote(inbox_id, safe='')}/messages/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Hearthstate dashboard",
        },
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def send_sign_in_email(delivery: dict[str, str]) -> dict:
    return send_message(build_message(delivery, kind="sign_in"))


def send_invitation_email(delivery: dict[str, str]) -> dict:
    return send_message(build_message(delivery, kind="invitation"))
