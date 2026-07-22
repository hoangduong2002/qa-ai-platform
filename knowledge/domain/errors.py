class KnowledgeError(RuntimeError):
    pass


class KnowledgeValidationError(KnowledgeError):
    pass


class KnowledgeNotFoundError(KnowledgeError):
    pass


class KnowledgePermissionError(KnowledgeError):
    pass
