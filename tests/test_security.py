import asyncio

from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token,
    decode_access_token,
)


def test_password_hash_round_trip() -> None:
    password = "secret"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed)


def test_token_encode_decode() -> None:
    token = create_access_token({"sub": "user@example.com"})
    email = decode_access_token(token)
    assert email == "user@example.com"
