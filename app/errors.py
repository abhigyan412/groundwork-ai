"""Turn request validation failures into 400s with specific, friendly messages.

FastAPI's default is a 422 with Pydantic internals; docs/api-contracts.md specifies 400 and
human-readable errors. Response shape:

    {"detail": "<first error, one sentence>", "errors": [{"field": "email", "message": "..."}]}

`detail` is what most clients show; `errors` lets the frontend place messages next to fields.
"""

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

_FIELD_LABELS = {
    "org_name": "Organization name",
    "email": "Email",
    "password": "Password",
    "question": "Question",
    "token": "Token",
}


def _field_of(loc: tuple) -> str | None:
    # loc looks like ("body", "email") or ("query", "limit"); a bare ("body",) is the whole body.
    parts = [str(p) for p in loc[1:] if not isinstance(p, int)]
    return ".".join(parts) or None


def _message(err: dict) -> str:
    field = _field_of(tuple(err.get("loc", ())))
    label = _FIELD_LABELS.get(field or "", (field or "Request").replace("_", " ").capitalize())
    kind = err.get("type", "")
    msg = str(err.get("msg", "is invalid"))

    if kind == "missing":
        return f"{label} is required."
    if kind == "json_invalid":
        return "Request body must be valid JSON."
    if kind in ("model_attributes_type", "dict_type"):
        return "Request body must be a JSON object."
    if field == "email" and kind == "value_error":
        return "Enter a valid email address."
    if kind == "string_too_short":
        if err.get("ctx", {}).get("min_length") == 1:
            return f"{label} can't be empty."
        return f"{label} must be at least {err['ctx']['min_length']} characters."
    if kind == "string_too_long":
        return f"{label} must be at most {err['ctx']['max_length']} characters."
    if kind == "value_error":
        # Our own validators raise ValueError("Password must be ..."); Pydantic prefixes it.
        return msg.removeprefix("Value error, ").rstrip(".") + "."
    return f"{label}: {msg}."


async def _validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = [
        {"field": _field_of(tuple(e.get("loc", ()))), "message": _message(e)} for e in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "detail": errors[0]["message"] if errors else "Invalid request.",
            "errors": errors,
        },
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_handler)  # type: ignore[arg-type]
