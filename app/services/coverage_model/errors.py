class CoverageModelError(RuntimeError):
    """Base error for Phase 7 coverage-model processing."""


class CoverageModelConfigurationError(CoverageModelError):
    """Raised when coverage-model configuration is invalid."""


class CoverageModelBuildError(CoverageModelError):
    """Raised when enabled coverage-model generation fails."""
