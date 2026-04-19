from app.core.db.base import Base
from app.core.db.registry import import_all_models


def test_metadata_contains_expected_tables() -> None:
    import_all_models()

    table_names = set(Base.metadata.tables.keys())

    assert "users" in table_names
    assert "organisations" in table_names
    assert "memberships" in table_names
