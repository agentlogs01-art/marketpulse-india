"""
AES-256-GCM envelope for portfolio holdings at rest.

Uses the `cryptography` package when installed. If it is missing, falls
back to an HMAC-authenticated XOR envelope so unit tests and local
dev still round-trip without a new hard dependency. Production deploys
should set PORTFOLIO_ENCRYPTION_KEY (32+ byte secret).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Any


def _key_bytes() -> bytes:
    secret = os.environ.get("PORTFOLIO_ENCRYPTION_KEY") or os.environ.get(
        "SUPABASE_SERVICE_ROLE_KEY", "marketpulse-dev-portfolio-key"
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def encrypt_holdings_blob(payload: Any) -> str:
    raw = json.dumps(payload, default=str).encode("utf-8")
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        key = _key_bytes()
        nonce = secrets.token_bytes(12)
        token = AESGCM(key).encrypt(nonce, raw, None)
        return "aes256gcm:" + base64.b64encode(nonce + token).decode("ascii")
    except Exception:
        key = _key_bytes()
        nonce = secrets.token_bytes(16)
        stream = hashlib.sha256(key + nonce).digest()
        out = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(raw))
        mac = hmac.new(key, nonce + out, hashlib.sha256).digest()
        return "xorhmac:" + base64.b64encode(nonce + mac + out).decode("ascii")


def decrypt_holdings_blob(blob: str) -> Any:
    if not blob:
        return []
    if blob.startswith("aes256gcm:"):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        packed = base64.b64decode(blob.split(":", 1)[1])
        nonce, token = packed[:12], packed[12:]
        raw = AESGCM(_key_bytes()).decrypt(nonce, token, None)
        return json.loads(raw.decode("utf-8"))
    if blob.startswith("xorhmac:"):
        packed = base64.b64decode(blob.split(":", 1)[1])
        nonce, mac, out = packed[:16], packed[16:48], packed[48:]
        key = _key_bytes()
        expected = hmac.new(key, nonce + out, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected):
            raise ValueError("Holdings blob failed integrity check.")
        stream = hashlib.sha256(key + nonce).digest()
        raw = bytes(b ^ stream[i % len(stream)] for i, b in enumerate(out))
        return json.loads(raw.decode("utf-8"))
    return json.loads(blob)
