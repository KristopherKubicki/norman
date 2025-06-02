class NormanError(Exception):
    """Base exception class for the Norman project."""



class ConfigurationError(NormanError):
    """Raised when there's an issue with the configuration."""



class ChannelError(NormanError):
    """Raised when there's an issue with a channel or channel-related operation."""



class FilterError(NormanError):
    """Raised when there's an issue with a channel filter or filter-related operation."""



class ConnectorError(NormanError):
    """Raised when there's an issue with a connector or connector-related operation."""



class BotError(NormanError):
    """Raised when there's an issue with a bot or bot-related operation."""



class DatabaseError(NormanError):
    """Raised when a database operation fails."""



class APIError(NormanError):
    """Raised when an unexpected API error occurs."""



class AuthenticationError(NormanError):
    """Raised when authentication fails."""



class AuthorizationError(NormanError):
    """Raised when a user is not authorized to perform an action."""
