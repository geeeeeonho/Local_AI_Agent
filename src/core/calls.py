"""Call a collaborator with arguments it may or may not accept.

Progress callbacks and cancel checks were added to runtimes one at a time, so
the same operation is reachable through callees with different signatures: the
current backend, a retained launcher runtime, and the stubs the tests inject.
Passing the new argument unconditionally raises TypeError, and every place that
did so had wrapped the call in ``except Exception``, which turned the mistake
into a silently skipped service instead of a crash.

Dropping what the callee cannot take keeps one call site for both shapes and
keeps the failure visible when it is a real one.
"""
import inspect


def _accepted(fn):
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):   # C functions and some builtins
        return None
    if any(value.kind is value.VAR_KEYWORD for value in parameters.values()):
        return True                   # **kwargs takes anything
    return {name for name, value in parameters.items()
            if value.kind in (value.POSITIONAL_OR_KEYWORD, value.KEYWORD_ONLY)}


def accepts(fn, name) -> bool:
    """Would ``fn`` accept a keyword argument called ``name``?"""
    allowed = _accepted(fn)
    if allowed is None:
        return False
    return True if allowed is True else name in allowed


def invoke(fn, *args, **optional):
    """Call ``fn(*args)`` with the ``optional`` keywords it actually accepts."""
    allowed = _accepted(fn)
    if allowed is None:
        return fn(*args)
    if allowed is True:
        return fn(*args, **optional)
    return fn(*args, **{name: value for name, value in optional.items()
                        if name in allowed})


__all__ = ['accepts', 'invoke']
