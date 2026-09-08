"""Local_AI_Agent launcher package.

Canonical layers:
    launcher.config         - product constants
    launcher.presenter.*    - TUI/GUI presentation abstraction
    launcher.services.*     - external service helpers
    launcher.actions.*      - reachable menu actions
    launcher.app            - application controller
    launcher.__main__       - entrypoint

Retired compatibility modules such as ``launcher.gui`` and
``launcher.checkbox`` are intentionally not part of the runtime API. New code
uses the Presenter interfaces directly.
"""
