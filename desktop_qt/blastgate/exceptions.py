"""
Custom exception hierarchy for Blastgate application
"""


class BlastgateError(Exception):
    """Base exception for all Blastgate errors"""
    pass


class NetworkError(BlastgateError):
    """Network communication errors"""
    pass


class HubOfflineError(NetworkError):
    """Hub is not reachable"""
    pass


class HubCommandError(NetworkError):
    """Hub returned error response"""
    pass


class ConfigurationError(BlastgateError):
    """Configuration validation errors"""
    pass


class ValidationError(BlastgateError):
    """Input validation errors"""
    pass
