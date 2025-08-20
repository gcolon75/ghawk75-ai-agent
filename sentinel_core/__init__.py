"""
Core package for the DeskSentinel agent.

This package contains modules responsible for interacting with external data
providers (stock and game pricing), applying alert rules, sending
notifications, managing persistence and exposing a simple web interface.

To run the agent interactively:
>>> python -m sentinel_core.main

"""

from importlib.metadata import version as _version

__all__ = [
    "__version__",
]

try:
    __version__ = _version("ghawk75-ai-agent")  # type: ignore [misc]
except Exception:
    __version__ = "0.0.0"
