from __future__ import annotations

import argparse
import asyncio

from app.core.db.session import async_session_factory
from app.core.errors.exceptions import ConflictError
from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.platform.services.platform_staff import PlatformStaffService
from app.users.models.user import UserStatus
from app.users.repositories.users import UserRepository


async def _run(email: str) -> None:
    async with async_session_factory() as session:
        async with session.begin():
            user = (await session.execute(__import__('sqlalchemy').select(UserRepository(session).session.bind))).scalar_one_or_none()
            repo = UserRepository(session)
            user = (await session.execute(__import__('sqlalchemy').select(__import__('app.users.models.user', fromlist=['User']).User).where(__import__('app.users.models.user', fromlist=['User']).User.email == email))).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"User with email {email} not found")
            if user.status == UserStatus.SUSPENDED.value:
                raise SystemExit("User is suspended")
            staff = await PlatformStaffRepository(session).get_by_user_id(user.id)
            if staff is not None:
                if staff.role == PlatformRole.PLATFORM_ADMIN.value and staff.status == 'active':
                    print('Already active platform admin')
                    return
                raise ConflictError(detail='Platform staff already exists; resolve manually')
            await PlatformStaffService(session).create_platform_staff(user_id=user.id, role=PlatformRole.PLATFORM_ADMIN)
            print('Platform admin created')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    asyncio.run(_run(args.email))


if __name__ == '__main__':
    main()
