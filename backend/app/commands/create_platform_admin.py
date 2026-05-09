from __future__ import annotations

from app.commands.make_platform_admin import main, make_platform_admin


async def create_platform_admin_by_email(email: str) -> None:
    await make_platform_admin(email)


# Backward-compatible alias for existing imports in tests/scripts.
_run = create_platform_admin_by_email


if __name__ == "__main__":
    raise SystemExit(main())
