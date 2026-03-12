"""
auth_helper.py — Multi-user JWT authentication for shop floor login.

User store priority (first match wins):
  1. Azure Table Storage (`users` table) — managed via admin page
  2. SHOP_FLOOR_USERS app setting (JSON array) — migration fallback
  3. SHOP_FLOOR_USERNAME / SHOP_FLOOR_PASSWORD_HASH — legacy single-user fallback

Tokens expire after 8 hours (one shift).
JWT payload includes: sub (username), display_name, role, iat, exp.
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

# In-memory user cache — avoids hitting Table Storage on every request
_user_cache = None
_user_cache_time = 0
_USER_CACHE_TTL = 300  # 5 minutes

# Rate limiting for login — 5 failures per username in 5 min triggers 60s cooldown
_login_failures = {}  # {username: [timestamp, timestamp, ...]}
_MAX_FAILURES = 5
_FAILURE_WINDOW = 300  # 5 minutes
_COOLDOWN = 60  # seconds


def check_rate_limit(username):
    """Returns True if the user is rate-limited (too many failed login attempts)."""
    now = time.time()
    attempts = _login_failures.get(username, [])
    # Prune old attempts outside the window
    attempts = [t for t in attempts if now - t < _FAILURE_WINDOW]
    _login_failures[username] = attempts

    if len(attempts) >= _MAX_FAILURES:
        # Check if last failure was within cooldown period
        if now - attempts[-1] < _COOLDOWN:
            return True
    return False


def record_login_failure(username):
    """Record a failed login attempt for rate limiting."""
    now = time.time()
    if username not in _login_failures:
        _login_failures[username] = []
    _login_failures[username].append(now)


def clear_login_failures(username):
    """Clear failure history after a successful login."""
    _login_failures.pop(username, None)


def _get_users_from_table():
    """Load all users from the `users` Azure Table Storage table.

    Returns list of dicts: [{username, display_name, password_hash, role}, ...]
    Returns None if table doesn't exist or can't be reached (caller falls back).
    """
    try:
        from azure.data.tables import TableServiceClient
        from azure.identity import DefaultAzureCredential

        # Match the hardcoded storage account in function_app.py
        storage_account = os.environ.get("STORAGE_ACCOUNT", "stj6lw7vswhnnhw")

        endpoint = f"https://{storage_account}.table.core.windows.net"
        credential = DefaultAzureCredential()
        service = TableServiceClient(endpoint=endpoint, credential=credential)
        service.create_table_if_not_exists("users")
        table = service.get_table_client("users")

        users = []
        for entity in table.list_entities():
            users.append({
                "username": entity["RowKey"],
                "display_name": entity.get("display_name", entity["RowKey"]),
                "password_hash": entity.get("password_hash", ""),
                "role": entity.get("role", "user"),
            })
        return users if users else None  # None triggers fallback if table is empty

    except Exception as e:
        logger.warning(f"Could not load users from Table Storage: {e}")
        return None


def _get_users_from_app_setting():
    """Load users from SHOP_FLOOR_USERS app setting (JSON array).

    Expected format:
    [{"username": "shopfloor", "display_name": "Shop Floor", "password_hash": "...", "role": "user"}]
    """
    raw = os.environ.get("SHOP_FLOOR_USERS", "")
    if not raw:
        return None
    try:
        users = json.loads(raw)
        if isinstance(users, list) and users:
            return users
    except json.JSONDecodeError as e:
        logger.error(f"SHOP_FLOOR_USERS JSON parse error: {e}")
    return None


def _get_legacy_user():
    """Build a single-user list from legacy SHOP_FLOOR_USERNAME/PASSWORD_HASH env vars."""
    username = os.environ.get("SHOP_FLOOR_USERNAME", "")
    password_hash = os.environ.get("SHOP_FLOOR_PASSWORD_HASH", "")
    if username and password_hash:
        return [{
            "username": username,
            "display_name": username.title(),
            "password_hash": password_hash,
            "role": "user",
        }]
    return None


def get_all_users():
    """Get the user list from the best available source (cached 5 min).

    Priority: Table Storage → SHOP_FLOOR_USERS app setting → legacy env vars.
    Returns list of user dicts, or empty list if nothing is configured.
    """
    global _user_cache, _user_cache_time

    now = time.time()
    if _user_cache is not None and (now - _user_cache_time) < _USER_CACHE_TTL:
        return _user_cache

    # Try each source in priority order
    users = _get_users_from_table()
    if users is None:
        users = _get_users_from_app_setting()
    if users is None:
        users = _get_legacy_user()
    if users is None:
        users = []

    _user_cache = users
    _user_cache_time = now
    return users


def invalidate_user_cache():
    """Force next get_all_users() call to reload from source."""
    global _user_cache, _user_cache_time
    _user_cache = None
    _user_cache_time = 0


def get_user_info(username):
    """Look up a single user by username. Returns user dict or None."""
    for user in get_all_users():
        if user["username"] == username:
            return user
    return None


def _verify_password(password, stored_hash):
    """Verify a password against a PBKDF2-SHA256 hash (iterations$salt$hash)."""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False

        iterations = int(parts[0])
        salt = base64.b64decode(parts[1])
        expected = base64.b64decode(parts[2])

        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)

    except Exception as e:
        logger.error(f"Password verification failed: {e}")
        return False


def authenticate_user(username, password):
    """Check username/password against user registry.

    Returns user dict (username, display_name, role) on success, None on failure.
    """
    user = get_user_info(username)
    if user is None:
        return None

    if _verify_password(password, user["password_hash"]):
        return {
            "username": user["username"],
            "display_name": user["display_name"],
            "role": user["role"],
        }
    return None


def create_token(username, display_name="", role="user"):
    """Create a JWT token (HS256) with 8-hour expiry.

    Payload includes display_name and role so the frontend can show
    who's logged in and control admin-only features without an API call.
    """
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise ValueError("JWT_SECRET app setting not configured")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "display_name": display_name or username,
        "role": role,
        "iat": now,
        "exp": now + TOKEN_EXPIRY_SECONDS,
    }

    h = _b64url_encode(json.dumps(header).encode())
    p = _b64url_encode(json.dumps(payload).encode())
    signing_input = f"{h}.{p}"

    sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    s = _b64url_encode(sig)

    return f"{h}.{p}.{s}"


def require_auth(req):
    """Validate Authorization header on incoming request.

    Returns the JWT payload dict on success (contains sub, display_name, role).
    Returns a JSONResponse with 401 on failure.

    Usage in endpoints:
        auth_result = auth_helper.require_auth(req)
        if isinstance(auth_result, JSONResponse):
            return auth_result
        # auth_result is now the payload dict
        username = auth_result["sub"]
        display_name = auth_result.get("display_name", username)
    """
    from azurefunctions.extensions.http.fastapi import JSONResponse

    auth_header = req.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    token = auth_header[7:]  # Strip "Bearer "
    payload = _verify_token(token)
    if payload is None:
        return JSONResponse({"error": "Invalid or expired token"}, status_code=401)

    # Return the full payload — endpoints can read username, display_name, role
    return payload


def require_admin(req):
    """Validate auth AND require admin role. Returns payload dict or 401/403 JSONResponse."""
    from azurefunctions.extensions.http.fastapi import JSONResponse

    result = require_auth(req)
    # If it's a dict, auth passed — check role
    if isinstance(result, dict):
        if result.get("role") != "admin":
            return JSONResponse({"error": "Admin access required"}, status_code=403)
    return result


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
        signing_input = f"{h}.{p}"
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
        actual_sig = _b64url_decode(s)

        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

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
    """Utility: generate a PBKDF2-SHA256 hash for storing in Table Storage or app settings.

    Usage: python -c "from auth_helper import generate_password_hash; print(generate_password_hash('your-password'))"
    """
    salt = os.urandom(32)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{iterations}${base64.b64encode(salt).decode()}${base64.b64encode(hash_bytes).decode()}"
