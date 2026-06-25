from fastapi import Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    import traceback
    import structlog
    log = structlog.get_logger()
    log.error(
        "unhandled_exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=str(request.url.path),
        traceback=traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )
