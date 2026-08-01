"""
The Maid — Face embedding encryption at rest.

Uses Fernet (cryptography library) with a key derived from a stable machine
identifier, a user-specific salt from settings, and a random DB salt stored
alongside the face-index.db SQLite file in schema_meta.

Encryption is mandatory. If the cryptography library is unavailable, the
FaceClusterer refuses to initialize and surfaces a clear error so embeddings are
never stored as plaintext.

This is lightweight column-level encryption for the face-index.db SQLite file.
It does NOT protect against a running, authenticated user process — it protects
biometric embeddings at rest from casual file access.
"""

import base64
import getpass
import hashlib
import json
import logging
import os
import platform
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SALT_LENGTH = 16
PBKDF2_ITERATIONS = 100_000

CRYPTO_AVAILABLE = False
Fernet = None  # type: ignore
PBKDF2HMAC = None  # type: ignore
hashes = None  # type: ignore

try:
    from cryptography.fernet import Fernet as _Fernet  # type: ignore
    from cryptography.hazmat.primitives import hashes as _hashes  # type: ignore
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC as _PBKDF2HMAC  # type: ignore

    Fernet = _Fernet
    hashes = _hashes
    PBKDF2HMAC = _PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except (ImportError, ModuleNotFoundError) as _crypto_import_error:  # pragma: no cover
    logger.debug("cryptography not available: %s", _crypto_import_error)


def _user_salt_from_settings() -> bytes:
    """
    Return a stable per-user salt derived from the Tauri settings file path.

    The settings file lives at ~/.the-maid/settings.json and is created with 0o600
    permissions. Using its path as a salt component ensures each user profile
    produces a different encryption key even when machine identifiers collide
    (containers, cloned VMs, multi-user systems).
    """
    settings_path = str(Path.home() / ".the-maid" / "settings.json")
    return hashlib.sha256(settings_path.encode("utf-8")).digest()


def _machine_id() -> str:
    """
    Return a stable-ish machine identifier for single-user desktop key derivation.

    ponytail: stdlib only, no extra deps. Tries /etc/machine-id (Linux), MAC
    address, hostname, and username. Falls back to a constant so we never derive
    from an empty string.
    """
    parts: list[str] = []

    try:
        with open("/etc/machine-id", "r", encoding="utf-8") as f:
            linux_id = f.read().strip()
            if linux_id:
                parts.append(linux_id)
    except (OSError, UnicodeDecodeError):
        pass

    node = uuid.getnode()
    if node:
        parts.append(f"{node:012x}")

    hostname = platform.node()
    if hostname:
        parts.append(hostname)

    try:
        parts.append(getpass.getuser())
    except (OSError, KeyError):
        pass

    if not parts:
        parts.append("the-maid-fallback-machine-id")

    return "|".join(parts)


def _derive_fernet_key(machine_id: str, db_salt: bytes, user_salt: bytes) -> bytes:
    """Derive a Fernet-compatible key from machine_id + db_salt + user_salt."""
    if PBKDF2HMAC is None or hashes is None:  # pragma: no cover
        raise RuntimeError("cryptography not available")
    material = hashlib.sha256(
        machine_id.encode("utf-8") + user_salt
    ).digest()
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=db_salt,
        iterations=PBKDF2_ITERATIONS,
    )
    raw_key = kdf.derive(material)
    return base64.urlsafe_b64encode(raw_key)


def _load_salt(conn) -> Optional[bytes]:
    """Load existing salt from schema_meta."""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'encryption_salt'"
    ).fetchone()
    if not row or row[0] is None:
        return None
    try:
        return base64.b64decode(row[0])
    except Exception:
        return None


def _create_salt(conn) -> bytes:
    """Generate and persist a new random salt."""
    salt = os.urandom(SALT_LENGTH)
    encoded = base64.b64encode(salt).decode("ascii")
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('encryption_salt', ?)",
        (encoded,),
    )
    return salt


def _get_or_create_salt(conn) -> Optional[bytes]:
    """Return existing salt or create one."""
    salt = _load_salt(conn)
    if salt is not None and len(salt) == SALT_LENGTH:
        return salt
    return _create_salt(conn)


class FaceEmbeddingCipher:
    """Transparent encrypt/decrypt wrapper for face embedding blobs."""

    def __init__(self, conn):
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography is required for face embedding encryption"
            )

        db_salt = _get_or_create_salt(conn)
        if db_salt is None:
            raise RuntimeError("could not create encryption salt")

        key = _derive_fernet_key(_machine_id(), db_salt, _user_salt_from_settings())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt plaintext bytes."""
        return self._fernet.encrypt(plaintext)

    def decrypt(self, ciphertext: bytes) -> bytes:
        """Decrypt ciphertext bytes. Raises on bad ciphertext."""
        return self._fernet.decrypt(ciphertext)
