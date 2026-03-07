from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from saki_api.core import security
from saki_api.core.exceptions import InternalServerErrorAppException
from saki_api.modules.access.service.auth import AuthService
from saki_api.modules.access.service.user import UserService


@pytest.mark.anyio
async def test_user_service_change_password_updates_hashed_password_field() -> None:
    service = object.__new__(UserService)
    repository = SimpleNamespace(update_or_raise=AsyncMock(return_value=object()))
    service.repository = repository

    user_id = uuid.uuid4()
    result = await UserService.change_password.__wrapped__(  # type: ignore[attr-defined]
        service,
        user_id,
        "argon2-hash",
        False,
    )

    assert result is not None
    repository.update_or_raise.assert_awaited_once_with(
        user_id,
        {
            "hashed_password": "argon2-hash",
            "must_change_password": False,
        },
    )


@pytest.mark.anyio
async def test_auth_service_change_password_raises_when_post_verify_fails() -> None:
    old_password = "a" * 64
    new_password = "b" * 64
    user_id = uuid.uuid4()

    current_user = SimpleNamespace(
        id=user_id,
        hashed_password=security.get_password_hash(old_password),
    )
    stale_user_after_update = SimpleNamespace(
        id=user_id,
        hashed_password=current_user.hashed_password,
    )

    fake_user_service = SimpleNamespace(
        get_by_id=AsyncMock(return_value=current_user),
        change_password=AsyncMock(return_value=stale_user_after_update),
    )

    service = object.__new__(AuthService)
    service.user_service = fake_user_service

    with pytest.raises(InternalServerErrorAppException, match="Password change verification failed"):
        await AuthService.change_password.__wrapped__(  # type: ignore[attr-defined]
            service,
            user_id,
            old_password,
            new_password,
        )

    fake_user_service.change_password.assert_awaited_once()
    args = fake_user_service.change_password.await_args.args
    assert args[0] == user_id
    assert args[2] is False
    assert security.verify_password(new_password, args[1]) is True
