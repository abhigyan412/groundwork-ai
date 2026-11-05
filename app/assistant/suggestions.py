"""Suggested questions for the widget, built from the org's own documents (no LLM).

Candidates come from numbered section headings ("1. Curfew" in Hostel_Policy.pdf → "What does the
Hostel Policy say about curfew?"). Each candidate must pass the strict groundedness gate before it
is offered: a suggestion the assistant then refuses is worse than no suggestion. Results are cached
per org and rebuilt when its ready documents change.
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

import asyncpg

from app.retrieval.search import passes_gate, retrieve

_HEADING = re.compile(r"^\d+(?:\.\d+)*\.?\s+([A-Z][A-Za-z][A-Za-z ,'&/()-]{1,48})$")
_GENERIC = frozenset(
    "purpose scope introduction overview contents definitions general summary background".split()
)


def _title(filename: str) -> str:
    stem = filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
    return " ".join(stem.split())


def _topic(heading: str) -> str:
    """'Accommodation fees' → 'accommodation fees'; keeps acronyms ('WFH rules')."""
    words = heading.split()
    first = words[0]
    if not first.isupper():
        first = first[0].lower() + first[1:]
    return " ".join([first, *words[1:]])


def _verb(title: str) -> str:
    """'Scholarship Rules' / 'Exam Regulations' → 'do'; 'Hostel Policy' → 'does'."""
    last = title.split()[-1] if title.split() else ""
    return "do" if last.endswith("s") and not last.endswith("ss") else "does"


def candidate_questions(docs: list[tuple[str, list[str]]]) -> list[str]:
    """docs: (filename, chunk texts in page order). Round-robin across documents."""
    per_doc: list[list[str]] = []
    for filename, texts in docs:
        title = _title(filename)
        seen: set[str] = set()
        questions: list[str] = []
        for text in texts:
            for line in text.splitlines():
                m = _HEADING.match(line.strip())
                if not m:
                    continue
                heading = m.group(1).strip(" ,")
                key = heading.lower()
                if key in seen or key in _GENERIC:
                    continue
                seen.add(key)
                questions.append(f"What {_verb(title)} the {title} say about {_topic(heading)}?")
        if questions:
            per_doc.append(questions)
    out: list[str] = []
    for i in range(max((len(q) for q in per_doc), default=0)):
        out.extend(q[i] for q in per_doc if i < len(q))
    return out


@dataclass
class SuggestionCache:
    entries: dict[UUID, tuple[tuple, list[str]]] = field(default_factory=dict)


async def _fingerprint(conn: asyncpg.Connection, org_id: UUID) -> tuple[int, datetime | None]:
    r = await conn.fetchrow(
        "SELECT count(*) AS n, max(updated_at) AS latest FROM documents"
        " WHERE org_id = $1 AND status = 'ready'",
        org_id,
    )
    return (r["n"], r["latest"])


async def _documents(conn: asyncpg.Connection, org_id: UUID) -> list[tuple[str, list[str]]]:
    rows = await conn.fetch(
        """
        SELECT d.filename, c.text
        FROM documents d JOIN chunks c ON c.document_id = d.id AND c.org_id = d.org_id
        WHERE d.org_id = $1 AND d.status = 'ready'
        ORDER BY d.created_at, d.id, c.page
        """,
        org_id,
    )
    docs: dict[str, list[str]] = {}
    for r in rows:
        docs.setdefault(r["filename"], []).append(r["text"])
    return list(docs.items())


async def suggested_questions(
    engine, cache: SuggestionCache, org_id: UUID, limit: int
) -> list[str]:
    """Up to `limit` heading-based questions that clear the strict gate (cached per org)."""
    pool: asyncpg.Pool = engine.pool
    async with pool.acquire() as conn:
        fp = await _fingerprint(conn, org_id)
        cached = cache.entries.get(org_id)
        if cached and cached[0] == fp:
            return cached[1]
        docs = await _documents(conn, org_id)

    kept: list[str] = []
    for question in candidate_questions(docs)[: limit * 4]:
        result = await retrieve(
            pool, engine.embedder, engine.reranker, engine.settings, org_id=org_id, query=question
        )
        if passes_gate(result, engine.settings, None):  # strict gate: as a direct question
            kept.append(question)
        if len(kept) == limit:
            break
    cache.entries[org_id] = (fp, kept)
    return kept
