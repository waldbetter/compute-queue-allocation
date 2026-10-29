class AppError(Exception):
    def __init__(self, message: str, http_status: int = 400):
        super().__init__(message)
        self.message = message
        self.http_status = http_status


class NotFoundError(AppError):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(message, http_status=404)


class ConflictError(AppError):
    def __init__(self, message: str = "Resource conflict"):
        super().__init__(message, http_status=409)


class ValidationError(AppError):
    def __init__(self, message: str = "Validation failed"):
        super().__init__(message, http_status=400)