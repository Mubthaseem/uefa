"""Cryptographic, Token, and Security Utilities."""

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Any

import jwt
import pyotp
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from passlib.context import CryptContext

# Password hashing with Argon2id
pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__type="ID",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=4
)

# Crockford Base32 alphabet: 32 symbols (omits I, L, O, U)
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CROCKFORD_SET = set(CROCKFORD_ALPHABET)


# =====================================================================
# Crockford Code Utilities (Rules N3, Section 6.4)
# =====================================================================

def normalise_code(raw_code: str) -> str:
    """
    Normalise and validate access code string.
    
    Transforms input:
      - Strips leading/trailing whitespace
      - Converts to uppercase
      - Removes hyphens and spaces
      - Validates Crockford Base32 characters
      - Formats as XXXX-XXXX-XXXX-XXXX
    
    Raises ValueError on invalid length or characters.
    """
    if not raw_code:
        raise ValueError("Code cannot be empty")

    cleaned = raw_code.strip().upper()
    cleaned = re.sub(r"[\s\-]", "", cleaned)

    if len(cleaned) != 16:
        raise ValueError(f"Invalid code length: expected 16 characters, got {len(cleaned)}")

    for char in cleaned:
        if char not in CROCKFORD_SET:
            raise ValueError(f"Invalid character in code: {char}")

    # Re-insert hyphens every 4 characters
    return f"{cleaned[0:4]}-{cleaned[4:8]}-{cleaned[8:12]}-{cleaned[12:16]}"


def generate_crockford_code() -> str:
    """
    Generate a 16-character Crockford Base32 code with 80 bits of entropy.
    Format: XXXX-XXXX-XXXX-XXXX
    Uses CSPRNG secrets.choice with rejection-free sampling.
    """
    chars = [secrets.choice(CROCKFORD_ALPHABET) for _ in range(16)]
    return f"{''.join(chars[0:4])}-{''.join(chars[4:8])}-{''.join(chars[8:12])}-{''.join(chars[12:16])}"


def hmac_code(pepper: bytes, normalised_code: str) -> str:
    """
    Calculate HMAC-SHA256 hex digest of normalised code with pepper.
    """
    return hmac.new(
        pepper,
        normalised_code.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


# =====================================================================
# Argon2id Password Hashing
# =====================================================================

def hash_password(password: str) -> str:
    """Hash password using Argon2id."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against Argon2id hash."""
    return pwd_context.verify(plain_password, hashed_password)


# =====================================================================
# AES-256-GCM Encryption / Decryption (TOTP secrets & code export)
# =====================================================================

def encrypt_aes_gcm(plaintext: str, key_32_bytes: bytes) -> str:
    """
    Encrypt plaintext string using AES-256-GCM with a 12-byte random nonce.
    Returns standard Base64 string of nonce + ciphertext + tag.
    """
    if len(key_32_bytes) != 32:
        raise ValueError("AES-256-GCM key must be exactly 32 bytes")
    
    aesgcm = AESGCM(key_32_bytes)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("utf-8")


def decrypt_aes_gcm(encrypted_b64: str, key_32_bytes: bytes) -> str:
    """
    Decrypt Base64 AES-256-GCM payload.
    """
    if len(key_32_bytes) != 32:
        raise ValueError("AES-256-GCM key must be exactly 32 bytes")
    
    payload = base64.b64decode(encrypted_b64)
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(key_32_bytes)
    decrypted_bytes = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted_bytes.decode("utf-8")


# =====================================================================
# TOTP MFA Utilities
# =====================================================================

def generate_totp_secret() -> str:
    """Generate random Base32 TOTP secret."""
    return pyotp.random_base32()


def verify_totp(secret: str, code: str) -> bool:
    """Verify 6-digit TOTP code with +- 1 time window."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code.strip(), valid_window=1)


def get_totp_provisioning_uri(secret: str, email: str, issuer: str = "DayJournal") -> str:
    """Generate otpauth URI for QR code setup."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=issuer)


# =====================================================================
# EdDSA (Ed25519) Keypair and JWT Management
# =====================================================================

def generate_ed25519_keypair() -> tuple[str, str]:
    """
    Generate an Ed25519 keypair and return (private_pem, public_pem).
    """
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    ).decode("utf-8")

    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("utf-8")

    return private_pem, public_pem


# Global runtime keys cache for development / fallback
_runtime_keys: tuple[str, str] | None = None


def get_default_keypair(configured_priv: str, configured_pub: str) -> tuple[str, str]:
    """Return configured keys or generate persistent runtime keys."""
    global _runtime_keys
    if configured_priv and configured_pub:
        return configured_priv, configured_pub
    if _runtime_keys is None:
        _runtime_keys = generate_ed25519_keypair()
    return _runtime_keys


def sign_jwt(
    payload: dict[str, Any],
    private_key_pem: str,
    kid: str = "k1",
    expires_in_seconds: int = 900
) -> str:
    """
    Sign a JWT using EdDSA (Ed25519).
    Adds standard iat, exp claims and header kid.
    """
    now = int(time.time())
    token_claims = {
        **payload,
        "iat": now,
        "exp": now + expires_in_seconds
    }
    headers = {"kid": kid}
    return jwt.encode(
        payload=token_claims,
        key=private_key_pem,
        algorithm="EdDSA",
        headers=headers
    )


def verify_jwt(
    token: str,
    public_key_pem: str,
    expected_aud: str | None = None
) -> dict[str, Any]:
    """
    Verify EdDSA JWT signature, expiration, and audience.
    """
    options = {"verify_signature": True, "verify_exp": True}
    kwargs = {}
    if expected_aud:
        kwargs["audience"] = expected_aud
    else:
        options["verify_aud"] = False

    return jwt.decode(
        token,
        key=public_key_pem,
        algorithms=["EdDSA"],
        options=options,
        **kwargs
    )


# =====================================================================
# Refresh Token Primitives
# =====================================================================

def generate_opaque_token() -> str:
    """Generate 256-bit URL-safe opaque string (64 chars)."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> str:
    """Compute SHA-256 hex digest of opaque token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


# =====================================================================
# Signed Media URL Generation (Spec 6.8 & 5.13)
# =====================================================================

def sign_media_url(
    base_url: str,
    object_path: str,
    secret_bytes: bytes,
    expires_in_seconds: int = 600
) -> str:
    """
    Generate a signed URL for private storage assets with expiration.
    Returns: {base_url}/storage/v1/object/sign/{object_path}?token={hmac}&expires={expiry}
    """
    clean_base = base_url.rstrip("/")
    clean_path = object_path.lstrip("/")
    expiry = int(time.time()) + expires_in_seconds
    
    # Message to sign: path + expiry timestamp
    msg = f"{clean_path}:{expiry}".encode()
    sig = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()
    
    return f"{clean_base}/storage/v1/object/sign/{clean_path}?token={sig}&expires={expiry}"


def verify_signed_media_url(
    object_path: str,
    token: str,
    expires: int,
    secret_bytes: bytes
) -> bool:
    """
    Verify signature and freshness of signed media URL.
    """
    now = int(time.time())
    if now > expires:
        return False
    clean_path = object_path.lstrip("/")
    msg = f"{clean_path}:{expires}".encode()
    expected_sig = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(token, expected_sig)
