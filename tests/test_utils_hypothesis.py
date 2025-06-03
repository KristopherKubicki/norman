import uuid
import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st

from app.core import utils


@given(st.integers(min_value=1, max_value=20))
def test_generate_unique_id_unique(n: int) -> None:
    ids = {utils.generate_unique_id() for _ in range(n)}
    assert len(ids) == n
    for uid in ids:
        uuid.UUID(uid)


@given(
    st.dictionaries(st.text(min_size=1, max_size=5), st.integers(), max_size=10),
    st.sets(st.text(min_size=1, max_size=5), max_size=10),
)
def test_get_subdict_matches_comprehension(data, keys) -> None:
    result = utils.get_subdict(data, keys)
    expected = {k: v for k, v in data.items() if k in keys}
    assert result == expected
