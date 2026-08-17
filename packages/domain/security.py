"""API key generation/hashing (docs/architecture.md section 13).

API keys are high-entropy random tokens, not user passwords -- a fast hash
(SHA-256) is the correct choice here, not a slow password hash like bcrypt/
argon2. Slow hashing exists to blunt brute-force guessing against low-entropy
human-chosen secrets; a 256-bit random token has no guessable structure for a
slow hash to protect against, and using one would only add needless latency
to every authenticated request.
"""

from __future__ import annotations

import hashlib
import secrets

API_KEY_PREFIX = "sk_test_"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode()).hexdigest()
