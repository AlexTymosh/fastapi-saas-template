def import_all_models() -> None:
    import app.memberships.models.membership  # noqa: F401
    import app.organisations.models.organisation  # noqa: F401
    import app.users.models.user  # noqa: F401
