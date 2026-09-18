class InterpretationError(Exception):
    """Untrusted model output could not be validated."""


class ProviderError(Exception):
    """Provider failed; never expose its response or exception text."""


class InfeasibleError(Exception):
    """No schedule satisfies the interpreted constraints."""


class ScheduleError(Exception):
    """Independent replay rejected the proposed response."""
