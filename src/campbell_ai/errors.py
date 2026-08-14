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


class CampbellTimeoutError(CampbellAIError):
    """Raised when one answer exceeds its wall-clock budget.

    Separate from `CampbellBusyError`: the service was not overloaded, this single
    question took too long — usually a very broad time window, or a conversation whose
    accumulated context makes every turn slow. The caller should narrow the question
    rather than simply retry the identical one, so the guidance differs.
    """

    def __init__(self, message: str, elapsed_seconds: float = 0.0):
        super().__init__(message)
        self.elapsed_seconds = round(float(elapsed_seconds), 1)


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
