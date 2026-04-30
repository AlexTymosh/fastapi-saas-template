def import_all_models() -> None:
    import app.audit.models.audit_event  # noqa: F401
    import app.invites.models.invite  # noqa: F401
    import app.memberships.models.membership  # noqa: F401
    import app.organisations.models.organisation  # noqa: F401
    import app.platform.models.platform_staff  # noqa: F401
    import app.users.models.user  # noqa: F401
