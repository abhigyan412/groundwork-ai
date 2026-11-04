"""Private PDF storage: {STORAGE_DIR}/{org_id}/{document_id}.pdf.

Paths are built only from UUIDs, never from user-supplied filenames. Nothing here is served over
HTTP; visitors only ever see filename and page number.
"""

import os
from pathlib import Path
from uuid import UUID


def relative_path(org_id: UUID, document_id: UUID) -> str:
    return f"{org_id}/{document_id}.pdf"


def _resolve(storage_dir: Path, rel: str) -> Path:
    base = storage_dir.resolve()
    path = (base / rel).resolve()
    if base not in path.parents:  # defence in depth; rel is always built from UUIDs
        raise ValueError(f"Refusing path outside storage: {rel}")
    return path


def write_pdf(storage_dir: Path, rel: str, data: bytes) -> None:
    """Atomic write (temp file + rename), so a reader never sees half a file."""
    path = _resolve(storage_dir, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".pdf.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def read_pdf(storage_dir: Path, rel: str) -> bytes:
    return _resolve(storage_dir, rel).read_bytes()


def delete_pdf(storage_dir: Path, rel: str) -> None:
    _resolve(storage_dir, rel).unlink(missing_ok=True)
