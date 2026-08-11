import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from lifeos.domain import AgentCredential, SessionRecord, User, utcnow

_PASSWORD_ITERATIONS = 210_000
_SESSION_TTL = timedelta(hours=12)


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), salt, _PASSWORD_ITERATIONS
    )
    return f"pbkdf2_sha256${_PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class AuthService:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    def ensure_user(self, username: str, password: str) -> None:
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None:
                session.add(User(username=username, password_hash=hash_password(password)))
                session.commit()

    def ensure_agent(self, token: str, name: str = "jarvis") -> None:
        with self.session_factory() as session:
            credential = session.scalar(
                select(AgentCredential).where(AgentCredential.name == name)
            )
            if credential is None:
                session.add(AgentCredential(name=name, token_hash=hash_token(token)))
                session.commit()

    def create_session(self, username: str, password: str) -> tuple[str, bool]:
        with self.session_factory() as session:
            user = session.scalar(select(User).where(User.username == username))
            if user is None or not verify_password(password, user.password_hash):
                return "", False
            token = secrets.token_urlsafe(32)
            session.add(
                SessionRecord(
                    user_id=user.id,
                    token_hash=hash_token(token),
                    expires_at=utcnow() + _SESSION_TTL,
                )
            )
            session.commit()
            return token, True

    def get_session_username(self, token: str | None) -> str | None:
        if not token:
            return None
        with self.session_factory() as session:
            record = session.scalar(
                select(SessionRecord).where(SessionRecord.token_hash == hash_token(token))
            )
            if record is None or record.revoked_at is not None or as_utc(record.expires_at) <= utcnow():
                return None
            user = session.get(User, record.user_id)
            return user.username if user else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        with self.session_factory() as session:
            record = session.scalar(
                select(SessionRecord).where(SessionRecord.token_hash == hash_token(token))
            )
            if record is not None:
                record.revoked_at = utcnow()
                session.commit()

    def authenticate_agent(self, token: str | None) -> bool:
        if not token:
            return False
        with self.session_factory() as session:
            credential = session.scalar(
                select(AgentCredential).where(AgentCredential.token_hash == hash_token(token))
            )
            if credential is None or credential.revoked_at is not None:
                return False
            credential.last_used_at = utcnow()
            session.commit()
            return True
