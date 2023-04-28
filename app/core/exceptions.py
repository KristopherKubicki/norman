class NormanError(Exception):
    """
    Base exception class for the Norman project. All custom exceptions should inherit from this class.
    """
    pass


class ConfigurationError(NormanError):
    """
    Raised when there's an issue with the configuration.
    """
    pass


class ChannelError(NormanError):
    """
    Raised when there's an issue with a channel or channel-related operation.
    """
    pass


class ChannelFilterError(NormanError):
    """
    Raised when there's an issue with a channel filter or filter-related operation.
    """
    pass


class ConnectorError(NormanError):
    """
    Raised when there's an issue with a connector or connector-related operation.
    """
    pass


class BotError(NormanError):
    """
    Raised when there's an issue with a bot or bot-related operation.
    """
    pass
