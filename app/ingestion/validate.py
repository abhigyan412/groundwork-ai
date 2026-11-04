"""Upload validation. Every rejection carries the HTTP status and the message shown to the user."""

import re
import unicodedata
from dataclasses import dataclass

import pymupdf
from fastapi import UploadFile

_READ_CHUNK = 1024 * 1024


@dataclass
class UploadRejectedError(Exception):
    status_code: int
    message: str


def _mb(n_bytes: int) -> str:
    return f"{n_bytes / (1024 * 1024):.1f}".rstrip("0").rstrip(".")


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload, refusing anything over `max_bytes` without buffering past the limit."""
    limit_mb = _mb(max_bytes)
    if file.size is not None and file.size > max_bytes:
        raise UploadRejectedError(
            413, f"This PDF is {_mb(file.size)} MB. The limit is {limit_mb} MB."
        )
    parts: list[bytes] = []
    total = 0
    while chunk := await file.read(_READ_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise UploadRejectedError(413, f"This PDF is larger than the {limit_mb} MB limit.")
        parts.append(chunk)
    return b"".join(parts)


def inspect_pdf(data: bytes, max_pages: int) -> int:
    """Check the bytes are a readable PDF within the page limit. Returns the page count.

    CPU-bound (parses the file): call via asyncio.to_thread.
    """
    invalid = UploadRejectedError(400, "This file isn't a valid PDF.")
    # The PDF spec allows the header anywhere in the first 1024 bytes.
    if b"%PDF-" not in data[:1024]:
        raise invalid
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        raise invalid from None
    with doc:
        if doc.needs_pass:
            raise UploadRejectedError(
                400, "This PDF is password-protected. Remove the password and upload it again."
            )
        pages = doc.page_count
    if pages < 1:
        raise invalid
    if pages > max_pages:
        raise UploadRejectedError(400, f"This PDF has {pages} pages. The limit is {max_pages}.")
    return pages


_UNSAFE = re.compile(r"[\x00-\x1f\x7f<>:\"|?*]")


def clean_filename(raw: str | None) -> str:
    """Display name only (never used in storage paths): strip directories and control chars."""
    name = unicodedata.normalize("NFC", raw or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    if not name:
        return "document.pdf"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[: 200 - len(ext) - 1] + dot + ext) if dot and len(ext) <= 10 else name[:200]
    return name
