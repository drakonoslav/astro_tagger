"""Expected, user-facing errors. The CLI prints these without a traceback."""


class AstroTaggerError(Exception):
    """Base class for errors the user can fix."""


class ConfigError(AstroTaggerError):
    """Bad or missing configuration (site, agents)."""


class PlaceholderRequired(ConfigError):
    """The agent has no real trajectory; the caller must opt in to a placeholder."""


class KernelError(AstroTaggerError):
    """Problem with the ephemeris kernels or their index."""


class NoCoverageError(KernelError):
    """No indexed kernel covers the requested time."""


class SanityError(AstroTaggerError):
    """A computed state failed its plausibility check."""
