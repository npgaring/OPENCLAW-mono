"""Execution token: HMAC-SHA256 signed, TTL 300s."""
import base64
import hashlib
import hmac
import json
import time
from typing import Any, Optional, Tuple

from app.core.config import settings
from app.gate.policy import POLICY_VERSION

TOKEN_TTL_SECONDS = 300


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _base64url_decode(s: str) -> bytes:
    pad = 4 - len(s) % 4
    if pad != 4:
        s += "=" * pad
    return base64.urlsafe_b64decode(s)


def generate_execution_token(
    payload: dict,
    secret: Optional[str] = None,
    issued_at: Optional[int] = None,
    expires_at: Optional[int] = None,
) -> str:
    secret = secret or settings.integration_api_key
    now = int(time.time())
    issued_at = issued_at or now
    expires_at = expires_at or (issued_at + TOKEN_TTL_SECONDS)
    payload = {**payload, "issued_at": issued_at, "expires_at": expires_at}
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    return _base64url_encode(payload_bytes) + "." + _base64url_encode(sig)


def verify_execution_token(token: str, secret: Optional[str] = None) -> Tuple[bool, Optional[dict]]:
    secret = secret or settings.integration_api_key
    if "." not in token:
        return False, None
    payload_b64, sig_b64 = token.rsplit(".", 1)
    try:
        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return False, None
    expected_sig = hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).digest()
    if not hmac.compare_digest(_base64url_encode(expected_sig), sig_b64):
        return False, None
    if is_token_expired(payload):
        return False, None
    return True, payload


def is_token_expired(payload: dict, now: Optional[int] = None) -> bool:
    exp = payload.get("expires_at")
    if not exp:
        return True
    return (now or int(time.time())) >= exp


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
