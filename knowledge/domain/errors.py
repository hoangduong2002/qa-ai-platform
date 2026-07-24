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


class KnowledgeDeletionError(KnowledgeError):
    """Raised when an operational Knowledge Base cannot be safely removed."""


class KnowledgePackageError(KnowledgeValidationError):
    """Base error for package inspection or import validation."""


class KnowledgePackageSecurityError(KnowledgePackageError):
    """Raised when an archive violates a package security boundary."""
