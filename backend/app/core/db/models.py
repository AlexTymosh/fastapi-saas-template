"""Central SQLAlchemy model registry imports.

Import this module in non-HTTP entrypoints that need SQLAlchemy ORM mappings
without importing the FastAPI application.

The imports are intentionally unused: importing the model classes registers them
with SQLAlchemy's declarative registry so string-based relationships can resolve
reliably in CLI commands, background workers, dispatchers, tests, and Alembic.
"""

from app.audit.models.audit_event import AuditEvent
from app.invites.models.invite import Invite
from app.memberships.models.membership import Membership
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent
from app.platform.models.platform_staff import PlatformStaff
from app.users.models.user import User

__all__ = [
    "AuditEvent",
    "Invite",
    "Membership",
    "Organisation",
    "OutboxEvent",
    "PlatformStaff",
    "User",
]
