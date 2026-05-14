"""
Logger utility for Multi-Technical-Alerts.

Provides easy access to configured loggers throughout the application.
"""

import logging
from config.logging_config import get_logger as _get_logger

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.
    
    Args:
        name: Logger name (typically __name__ of calling module)
    
    Returns:
        Configured logger instance
    
    Usage:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Processing data...")
    """

    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
    )

    logger = _get_logger(name)

    logger.debug("Debug message")
    logger.info("Info message")

    return logger


class LoggerMixin:
    """
    Mixin class to add logging capability to any class.
    
    Usage:
        class MyClass(LoggerMixin):
            def process(self):
                self.logger.info("Processing...")
    """
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        return get_logger(self.__class__.__module__)
