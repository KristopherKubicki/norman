import pytest
from app.core import exceptions


@pytest.mark.parametrize(
    "exc",
    [
        exceptions.ConfigurationError,
        exceptions.ChannelError,
        exceptions.FilterError,
        exceptions.ConnectorError,
        exceptions.BotError,
        exceptions.DatabaseError,
        exceptions.APIError,
        exceptions.AuthenticationError,
        exceptions.AuthorizationError,
    ],
)
def test_subclass_of_norman_error(exc):
    assert issubclass(exc, exceptions.NormanError)
