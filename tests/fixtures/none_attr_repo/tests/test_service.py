from __future__ import annotations

from app.service import get_user_email


class Profile:
    def __init__(self, email: str) -> None:
        self.email = email


class User:
    def __init__(self, email: str) -> None:
        self.profile = Profile(email)


def test_get_user_email_returns_value() -> None:
    assert get_user_email(User("dev@example.com")) == "dev@example.com"


def test_get_user_email_handles_none() -> None:
    assert get_user_email(None) is None
