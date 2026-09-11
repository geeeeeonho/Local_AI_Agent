"""Standalone application using the shared desktop composition."""
from apps.shared.entry import main as run_app


def main(argv=None):
    return run_app('chat', argv)
