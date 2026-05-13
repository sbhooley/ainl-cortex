"""
Centralized Logging for Hooks

All hooks log to the same file for easy debugging.
"""

import logging
import json
from pathlib import Path
from typing import Any, Dict
import sys


# Set up log directory
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "hooks.log"


# Configure logger
logger = logging.getLogger("ainl_graph_memory_hooks")
logger.setLevel(logging.DEBUG)

# File handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Also log to stderr for development
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setLevel(logging.WARNING)
stderr_formatter = logging.Formatter('%(levelname)s: %(message)s')
stderr_handler.setFormatter(stderr_formatter)
logger.addHandler(stderr_handler)


def log_event(event_name: str, data: Dict[str, Any]) -> None:
    """
    Log a structured event.

    Args:
        event_name: Event identifier (e.g., "user_prompt_submit")
        data: Event data
    """
    logger.info(f"Event: {event_name} - {json.dumps(data)}")


def log_error(error_name: str, error: Exception, context: Dict[str, Any] = None) -> None:
    """
    Log an error with context.

    Args:
        error_name: Error identifier
        error: Exception object
        context: Additional context data
    """
    error_data = {
        "error": str(error),
        "type": type(error).__name__,
        "context": context or {}
    }
    logger.error(f"Error: {error_name} - {json.dumps(error_data)}", exc_info=True)


def get_logger(name: str) -> logging.Logger:
    """Get a child logger for a specific hook"""
    return logging.getLogger(f"ainl_graph_memory_hooks.{name}")
