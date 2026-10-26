"""Server Unit Tests S01 - S09 (Spec Section 11.1)."""

import pytest

from app.redis import InMemoryLimiter
from app.security import (
    CROCKFORD_ALPHABET,
    CROCKFORD_SET,
    decrypt_aes_gcm,
    encrypt_aes_gcm,
    generate_crockford_code,
    generate_ed25519_keypair,
    generate_totp_secret,
    hash_password,
    hmac_code,
    normalise_code,
    sign_jwt,
    sign_media_url,
    verify_jwt,
    verify_password,
    verify_totp,
)


def test_s01_code_entropy_and_crockford_charset():
    """S01: Crockford Base32 generator produces 16 symbols, 80 bits entropy, no ILOU."""
    # 32 characters in alphabet = log2(32) = 5 bits per char * 16 chars = 80 bits
    assert len(CROCKFORD_ALPHABET) == 32
    assert "I" not in CROCKFORD_SET
    assert "L" not in CROCKFORD_SET
    assert "O" not in CROCKFORD_SET
    assert "U" not in CROCKFORD_SET

    codes = [generate_crockford_code() for _ in range(100)]
    for code in codes:
        assert len(code) == 19  # XXXX-XXXX-XXXX-XXXX
        parts = code.split("-")
        assert len(parts) == 4
        for part in parts:
            assert len(part) == 4
            for char in part:
                assert char in CROCKFORD_SET


def test_s02_hmac_determinism():
    """S02: HMAC-SHA256 with pepper produces deterministic 64-char hex string."""
    pepper = b"test_pepper_bytes_for_unit_tests_1234567890"
    code = "7XKM-9VR1-CY4P-MW2A"

    h1 = hmac_code(pepper, code)
    h2 = hmac_code(pepper, code)
    assert h1 == h2
    assert len(h1) == 64

    # Different pepper produces distinct hash
    other_pepper = b"different_pepper_bytes_987654321"
    h3 = hmac_code(other_pepper, code)
    assert h1 != h3


def test_s03_jwt_eddsa_signature_and_expiration():
    """S03: EdDSA (Ed25519) token issuance and verification."""
    priv, pub = generate_ed25519_keypair()
    claims = {"sub": "device-123", "aud": "client", "ent": "member"}

    # Valid token
    token = sign_jwt(claims, priv, expires_in_seconds=60)
    decoded = verify_jwt(token, pub, expected_aud="client")
    assert decoded["sub"] == "device-123"
    assert decoded["ent"] == "member"

    # Audience mismatch
    with pytest.raises(Exception):
        verify_jwt(token, pub, expected_aud="admin")

    # Expired token
    expired_token = sign_jwt(claims, priv, expires_in_seconds=-10)
    with pytest.raises(Exception):
        verify_jwt(expired_token, pub, expected_aud="client")


def test_s04_argon2id_hashing():
    """S04: Argon2id password verification."""
    password = "SuperSecretAdminPassword123!"
    hashed = hash_password(password)

    assert hashed.startswith("$argon2id$")
    assert verify_password(password, hashed) is True
    assert verify_password("WrongPassword!", hashed) is False


def test_s05_totp_mfa():
    """S05: TOTP 6-digit generation and verification."""
    secret = generate_totp_secret()
    assert len(secret) == 32

    import pyotp
    totp = pyotp.TOTP(secret)
    current_code = totp.now()

    assert verify_totp(secret, current_code) is True
    assert verify_totp(secret, "000000") is False


def test_s06_normalise_code():
    """S06: Code normalisation cleans spacing/hyphens/casing and validates Crockford alphabet."""
    # Lowercase with mixed spaces and hyphens
    raw = "  7xkm 9vr1-cy4p mw2a  "
    normalised = normalise_code(raw)
    assert normalised == "7XKM-9VR1-CY4P-MW2A"

    # Already formatted
    assert normalise_code("7XKM-9VR1-CY4P-MW2A") == "7XKM-9VR1-CY4P-MW2A"

    # Invalid characters (e.g. letter 'O' or 'I' which are excluded from Crockford)
    with pytest.raises(ValueError, match="Invalid character in code"):
        normalise_code("7XKM-9VR1-CY4P-LW2O")

    # Invalid length
    with pytest.raises(ValueError, match="Invalid code length"):
        normalise_code("7XKM-9VR1")


def test_s07_aes_256_gcm_roundtrip():
    """S07: AES-256-GCM encryption and decryption round-trip."""
    key = b"01234567890123456789012345678901"  # exactly 32 bytes
    plaintext = "AB12-CD34-EF56-GH78"

    ciphertext = encrypt_aes_gcm(plaintext, key)
    assert ciphertext != plaintext

    decrypted = decrypt_aes_gcm(ciphertext, key)
    assert decrypted == plaintext


def test_s08_signed_media_urls():
    """S08: HMAC signed media URLs with expiration."""
    secret = b"url_signing_secret_32_bytes_long"
    base = "https://xyz.supabase.co"
    path = "member-media/video/ep1.mp4"

    url = sign_media_url(base, path, secret, expires_in_seconds=600)
    assert "https://xyz.supabase.co/storage/v1/object/sign/member-media/video/ep1.mp4?token=" in url
    assert "&expires=" in url


def test_s09_sliding_window_rate_limiter():
    """S09: Sliding-window rate limiter respects limits and lockouts."""
    limiter = InMemoryLimiter()
    key = "test_user_ip"

    # Allow 3 attempts in 10s
    assert limiter.check_rate_limit(key, limit=3, window_seconds=10)[0] is True
    assert limiter.check_rate_limit(key, limit=3, window_seconds=10)[0] is True
    assert limiter.check_rate_limit(key, limit=3, window_seconds=10)[0] is True

    # 4th attempt should be blocked
    allowed, remaining, _ = limiter.check_rate_limit(key, limit=3, window_seconds=10)
    assert allowed is False
    assert remaining == 0

    # Lockout test
    limiter.set_lockout(key, duration_seconds=60)
    assert limiter.is_locked_out(key) is True
