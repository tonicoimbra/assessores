"""Encryption utilities for sensitive data at rest (DLQ, checkpoints).

Uses Fernet symmetric encryption (AES-128-CBC + HMAC-SHA256).
Key must be a valid Fernet key: 32 url-safe base64-encoded bytes.
Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("assessor_ai")


def generate_key() -> str:
    """Generate a new random Fernet key (Base64 URL-safe, 44 chars).

    Use this once during setup and store in DLQ_ENCRYPTION_KEY.
    """
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
        return Fernet.generate_key().decode()
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca 'cryptography' não instalada. Execute: pip install cryptography>=42.0.0"
        ) from exc


def _get_fernet(key: str):  # type: ignore[return]
    """Return a Fernet instance for the given key string."""
    try:
        from cryptography.fernet import Fernet  # noqa: PLC0415
        from cryptography.exceptions import InvalidKey  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca 'cryptography' não instalada. Execute: pip install cryptography>=42.0.0"
        ) from exc

    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, Exception) as exc:
        raise ValueError(f"Chave Fernet inválida: {exc}") from exc


def encrypt_json(data: dict[str, Any], key: str) -> bytes:
    """Encrypt a dict as JSON using Fernet.

    Args:
        data: Dictionary to encrypt.
        key: Fernet key string (from DLQ_ENCRYPTION_KEY).

    Returns:
        Fernet-encrypted bytes (not human-readable).

    Raises:
        ValueError: If key is invalid.
    """
    if not key:
        # No key: return raw JSON bytes (plaintext – compatibility mode)
        return json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    plaintext = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    fernet = _get_fernet(key)
    return fernet.encrypt(plaintext)


def decrypt_json(blob: bytes, key: str) -> dict[str, Any]:
    """Decrypt a Fernet-encrypted blob back to a dict.

    Args:
        blob: Encrypted bytes produced by encrypt_json().
        key: Fernet key string (must match the encryption key).

    Returns:
        Decrypted dict.

    Raises:
        ValueError: If key is invalid or data is corrupted/tampered.
    """
    if not key:
        # No key: assume plaintext JSON
        return json.loads(blob.decode("utf-8"))

    try:
        from cryptography.fernet import InvalidToken  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca 'cryptography' não instalada. Execute: pip install cryptography>=42.0.0"
        ) from exc

    fernet = _get_fernet(key)
    try:
        plaintext = fernet.decrypt(blob)
    except InvalidToken as exc:
        raise ValueError(
            "Falha ao descriptografar arquivo DLQ: chave incorreta ou dados corrompidos."
        ) from exc

    return json.loads(plaintext.decode("utf-8"))


def encrypt_text(text: str, key: str) -> bytes:
    """Encrypt a plain text string using Fernet.

    Args:
        text: Plain text to encrypt.
        key: Fernet key string.

    Returns:
        Fernet-encrypted bytes.
    """
    if not key:
        return text.encode("utf-8")

    fernet = _get_fernet(key)
    return fernet.encrypt(text.encode("utf-8"))


def decrypt_text(blob: bytes, key: str) -> str:
    """Decrypt a Fernet-encrypted blob back to plain text.

    Args:
        blob: Encrypted bytes produced by encrypt_text().
        key: Fernet key string.

    Returns:
        Decrypted plain text.
    """
    if not key:
        return blob.decode("utf-8")

    try:
        from cryptography.fernet import InvalidToken  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "Biblioteca 'cryptography' não instalada. Execute: pip install cryptography>=42.0.0"
        ) from exc

    fernet = _get_fernet(key)
    try:
        return fernet.decrypt(blob).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError(
            "Falha ao descriptografar texto: chave incorreta ou dados corrompidos."
        ) from exc
