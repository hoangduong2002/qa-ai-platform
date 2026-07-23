class KnowledgeError(RuntimeError):
    pass


class KnowledgeValidationError(KnowledgeError):
    pass


class KnowledgeConflictError(KnowledgeValidationError):
    pass


class KnowledgeNotFoundError(KnowledgeError):
    pass


class KnowledgePermissionError(KnowledgeError):
    pass


class KnowledgePackageError(KnowledgeValidationError):
    """Base error for package inspection or import validation."""


class KnowledgePackageSecurityError(KnowledgePackageError):
    """Raised when an archive violates a package security boundary."""
