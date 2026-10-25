"""Accounts (F12): email + password sign-up / log-in and password reset.

Passwords are hashed with scrypt and a per-account salt. Each account owns one profile (a `Session` object
holding follows, alerts, Premium, …); every browser that logs in to the account points at that same profile.
In-memory for the MVP — swap for a database table.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import Session

RESET_TTL_MS = 30 * 60 * 1000


def _now() -> int:
    return int(time.time() * 1000)


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


@dataclass
class Account:
    email: str
    salt: bytes
    pw_hash: bytes
    profile: Session
    created_at: int
    consent_at: int  # when the terms & privacy policy were accepted


class Accounts:
    def __init__(self) -> None:
        self.by_email: dict[str, Account] = {}
        self.reset_tokens: dict[str, tuple[str, int]] = {}  # token -> (email, expires)

    @staticmethod
    def normalise(email: str) -> str:
        return email.strip().lower()

    def exists(self, email: str) -> bool:
        return self.normalise(email) in self.by_email

    def create(self, email: str, password: str, profile: Session) -> Account:
        salt = os.urandom(16)
        acc = Account(email=self.normalise(email), salt=salt, pw_hash=_hash(password, salt), profile=profile,
                      created_at=_now(), consent_at=_now())
        self.by_email[acc.email] = acc
        return acc

    def verify(self, email: str, password: str) -> Account | None:
        acc = self.by_email.get(self.normalise(email))
        # hash even when the account doesn't exist, so timing doesn't reveal which emails are registered
        candidate = _hash(password, acc.salt if acc else b"0" * 16)
        if acc and hmac.compare_digest(candidate, acc.pw_hash):
            return acc
        return None

    def set_password(self, acc: Account, password: str) -> None:
        acc.salt = os.urandom(16)
        acc.pw_hash = _hash(password, acc.salt)

    def issue_reset(self, email: str) -> str | None:
        acc = self.by_email.get(self.normalise(email))
        if acc is None:
            return None
        token = secrets.token_urlsafe(24)
        self.reset_tokens[token] = (acc.email, _now() + RESET_TTL_MS)
        return token

    def consume_reset(self, token: str) -> Account | None:
        email, expires = self.reset_tokens.pop(token, (None, 0))
        if email is None or expires < _now():
            return None
        return self.by_email.get(email)

    def delete(self, email: str | None) -> None:
        if email:
            self.by_email.pop(self.normalise(email), None)
            self.reset_tokens = {t: v for t, v in self.reset_tokens.items() if v[0] != email}
