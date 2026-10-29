"""Post-recompute object checks adapted from neka-nat/freecad-mcp (MIT)."""

_FAILED_STATES = {"invalid", "error", "touched"}


def _states(obj):
    try:
        value = obj.State
    except Exception:
        return []
    if isinstance(value, str):
        return [value]
    try:
        return [str(item) for item in value]
    except Exception:
        return []


def validity_error(obj):
    """Return a diagnostic for an invalid recomputed object, else ``None``."""
    name = str(getattr(obj, "Name", "<unknown>"))
    states = _states(obj)
    failed = [s for s in states if s.strip().casefold() in _FAILED_STATES]
    checker = getattr(obj, "isValid", None)
    try:
        valid = bool(checker()) if callable(checker) else True
    except Exception as exc:
        return "Object '%s' validity check failed: %s: %s" % (
            name, type(exc).__name__, exc)
    if valid and not failed:
        return None
    status = getattr(obj, "getStatusString", None)
    try:
        reason = str(status()).strip() if callable(status) else ""
    except Exception:
        reason = ""
    detail = (": " + reason) if reason else ""
    return "Object '%s' failed to compute%s (State: %s)" % (
        name, detail, ", ".join(states) if states else "unknown")


def require_valid(obj):
    problem = validity_error(obj)
    if problem:
        raise RuntimeError(problem)
    return obj

