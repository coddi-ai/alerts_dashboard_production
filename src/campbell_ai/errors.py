"""Domain exceptions used by Campbell AI."""


class CampbellAIError(Exception):
    """Base error for expected Campbell AI failures."""


class CampbellAuthenticationError(CampbellAIError):
    """Raised when the dashboard identity cannot be resolved."""


class CampbellAuthorizationError(CampbellAIError):
    """Raised when a dashboard user cannot access a client."""


class CampbellConfigurationError(CampbellAIError):
    """Raised when required runtime configuration is missing."""


class CampbellDataError(CampbellAIError):
    """Raised when the dashboard data contract is not available."""


class CampbellSessionError(CampbellAIError):
    """Raised when a session identifier is invalid."""
