"""
auth_helper.py — JWT authentication for shop floor login.

Simple username/password auth with stateless JWT tokens.
Credentials stored as app settings (SHOP_FLOOR_USERNAME, SHOP_FLOOR_PASSWORD_HASH, JWT_SECRET).
Tokens expire after 8 hours (one shift).
"""

import os
import logging
import hashlib
import hmac
import json
import base64
import time

logger = logging.getLogger(__name__)

# Token lifetime: 8 hours (one shift)
TOKEN_EXPIRY_SECONDS = 8 * 60 * 60


def authenticate_user(username, password):
    """Check username/password against app settings.

    Password is compared against a PBKDF2-SHA256 hash stored in SHOP_FLOOR_PASSWORD_HASH.
    Format: iterations$salt$hash (all base64-encoded where needed).

    Returns True if credentials match, False otherwise.
    """
    expected_username = os.environ.get("SHOP_FLOOR_USERNAME", "")
    stored_hash = os.environ.get("SHOP_FLOOR_PASSWORD_HASH", "")

    if not expected_username or not stored_hash:
        logger.error("Auth app settings not configured (SHOP_FLOOR_USERNAME or SHOP_FLOOR_PASSWORD_HASH)")
        return False

    if username != expected_username:
        return False

    try:
        # Parse stored hash: iterations$salt$hash
        parts = stored_hash.split("$")
        if len(parts) != 3:
            logger.error("SHOP_FLOOR_PASSWORD_HASH format invalid — expected iterations$salt$hash")
            return False

        iterations = int(parts[0])
        salt = base64.b64decode(parts[1])
        expected = base64.b64decode(parts[2])

        # Hash the provided password with the same salt and iterations
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)

    except Exception as e:
        logger.error(f"Password verification failed: {e}")
        return False


def create_token(username):
    """Create a JWT token (HS256) with 8-hour expiry.

    Uses a minimal hand-rolled JWT to avoid external dependencies.
    Structure: header.payload.signature (all base64url-encoded).
    """
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise ValueError("JWT_SECRET app setting not configured")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "iat": now,
        "exp": now + TOKEN_EXPIRY_SECONDS,
    }

    # Encode header and payload
    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{h}.{p}"

    # Sign with HMAC-SHA256
    sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    s = _b64url_encode(sig)

    return f"{h}.{p}.{s}"


def require_auth(req):
    """Validate Authorization header on incoming request.

    Returns None if valid, or a JSONResponse with 401 if invalid/missing.
    Call at the top of each protected endpoint.
    """
    from azurefunctions.extensions.http.fastapi import JSONResponse

    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    token = auth_header[7:]  # Strip "Bearer "
    payload = _verify_token(token)
    if payload is None:
        return JSONResponse({"error": "Invalid or expired token"}, status_code=401)

    return None  # Auth passed


def _verify_token(token):
    """Verify a JWT token's signature and expiry. Returns payload dict or None."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        return None

    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None

        h, p, s = parts
        # Verify signature
        signing_input = f"{h}.{p}"
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = _b64url_decode(s)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        # Decode payload and check expiry
        payload = json.loads(_b64url_decode(p))
        if payload.get("exp", 0) < int(time.time()):
            return None

        return payload

    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return None


def _b64url_encode(data):
    """Base64url encode bytes (no padding)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s):
    """Base64url decode string (re-add padding)."""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def generate_password_hash(password, iterations=600_000):
    """Utility: generate a PBKDF2-SHA256 hash for storing in app settings.

    Run locally once to generate the hash, then paste into Azure portal.
    Usage: python -c "from auth_helper import generate_password_hash; print(generate_password_hash('your-password'))"
    """
    salt = os.urandom(32)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${base64.b64encode(salt).decode()}${base64.b64encode(hash_bytes).decode()}"
