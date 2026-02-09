from typing import Optional

class GitHubAPIError(Exception):
    """Base for all GitHub API errors."""
    pass

# RECOVERABLE
class RetryableError(GitHubAPIError):
    """Can be retried."""
    pass

class RateLimitError(RetryableError):
    def __init__(self, message: str, reset_at: Optional[int] = None, resource: str = "core"):
        super().__init__(message)
        self.reset_at = reset_at
        self.resource = resource

class NetworkError(RetryableError):
    """Timeouts, connection errors."""
    pass

class ServerError(RetryableError):
    """5xx errors from GitHub."""
    pass

# FATAL
class FatalError(GitHubAPIError):
    """Should NOT be retried."""
    pass

class AuthenticationError(FatalError):
    pass

class NotFoundError(FatalError):
    """404 - repo/resource doesn't exist."""
    pass

class PermissionError(FatalError):
    """403 - insufficient permissions."""
    pass

# GRAPHQL
class GraphQLError(GitHubAPIError):
    def __init__(self, message: str, error_type: Optional[str] = None, path: list = None):
        super().__init__(message)
        self.error_type = error_type
        self.path = path

    @property
    def is_retryable(self) -> bool:
        # Common temporary errors in GitHub GraphQL
        return self.error_type in ["RATE_LIMITED", "somethings_wrong", "loading"]