import uuid

from app.core.utils import generate_unique_id, get_subdict


def test_generate_unique_id_returns_valid_uuid_and_is_unique():
    first = generate_unique_id()
    second = generate_unique_id()

    # Should return string representations of valid UUIDs
    uuid_first = uuid.UUID(first)
    uuid_second = uuid.UUID(second)

    assert str(uuid_first) == first
    assert str(uuid_second) == second

    # Ensure unique values between calls
    assert first != second


def test_get_subdict_filters_keys():
    data = {"a": 1, "b": 2, "c": 3}
    keys = {"a", "c", "missing"}

    result = get_subdict(data, keys)

    assert result == {"a": 1, "c": 3}
