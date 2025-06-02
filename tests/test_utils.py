import uuid
from app.core import utils


def test_generate_unique_id_unique() -> None:
    id1 = utils.generate_unique_id()
    id2 = utils.generate_unique_id()
    assert id1 != id2
    # Ensure returned value is valid UUID string
    uuid.UUID(id1)
    uuid.UUID(id2)


def test_get_subdict() -> None:
    data = {"a": 1, "b": 2, "c": 3}
    result = utils.get_subdict(data, {"a", "c"})
    assert result == {"a": 1, "c": 3}
