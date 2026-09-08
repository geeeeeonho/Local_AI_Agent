"""Canonical Open Interpreter App Server protocol surface used by the product.

The transport remains generic JSONL over stdio in :mod:`app_server_client`.
Keeping product-owned method names and initialize metadata here makes upstream
protocol drift visible in one place without wrapping the App Server in another
SDK layer.
"""
from __future__ import annotations

INITIALIZE = "initialize"
INITIALIZED = "initialized"
THREAD_START = "thread/start"
THREAD_RESUME = "thread/resume"
TURN_START = "turn/start"
TURN_INTERRUPT = "turn/interrupt"


def initialize_params() -> dict:
    """Return the Local_AI_Agent client handshake payload."""
    return {
        "clientInfo": {
            "name": "local_ai_agent",
            "title": "Local_AI_Agent",
            "version": "1",
        },
        "capabilities": {"experimentalApi": False},
    }


__all__ = [
    "INITIALIZE",
    "INITIALIZED",
    "THREAD_START",
    "THREAD_RESUME",
    "TURN_START",
    "TURN_INTERRUPT",
    "initialize_params",
]
