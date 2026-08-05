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


class CampbellBusyError(CampbellAIError):
    """Raised when the service cannot admit another request right now.

    Distinct from a configuration or data failure: nothing is broken, the caller only
    has to wait. `retry_after` is the seconds to wait, and `scope` says whether the
    limit hit was the user's own concurrency or the service-wide one, because the two
    need different wording in the UI.
    """

    def __init__(self, message: str, retry_after: int = 10, scope: str = "global"):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))
        self.scope = scope
