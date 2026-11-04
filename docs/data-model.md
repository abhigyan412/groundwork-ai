# Data Model [Proposed]

Postgres with pgvector. Every tenant-owned table carries `org_id`. The schema lives in `app/db/schema.sql` and is applied (idempotently) on API startup.

## Tables

### organizations
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| name | text | |
| created_at | timestamptz | |

### users
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK → organizations | one user per org for the MVP |
| email | text | unique on `lower(email)`; stored lower-cased |
| password_hash | text | Argon2id |
| created_at | timestamptz | |

### assistants
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| token_hash | text unique | SHA-256 of the token |
| token_encrypted | text | Fernet ciphertext, for re-display in the dashboard only (ADR 0007) |
| token_prefix | text | first chars, for display only |
| created_at | timestamptz | |
| revoked_at | timestamptz null | set on regeneration |

Partial unique index on `(org_id) WHERE revoked_at IS NULL`: at most one active assistant per org.

### documents
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| filename | text | original name, shown in references |
| storage_path | text | private path |
| size_bytes | int | |
| page_count | int null | null until the PDF is parsed |
| status | text | `processing` / `ready` / `failed` |
| error | text null | failure reason, shown to the user |
| pages_without_text | int[] | pages with no extractable text (flagged; OCR is out of scope) |
| generation | int | bumped on replace; processing results for an older generation are discarded |
| updated_at | timestamptz | |
| created_at | timestamptz | |

### chunks
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | denormalized so retrieval filters without a join |
| document_id | uuid FK → documents ON DELETE CASCADE | |
| page | int | 1-based |
| text | text | |
| embedding | vector(384) | dimension depends on embedding model |
| tsv | tsvector | generated: `to_tsvector('english', text)` |

Indexes: `(org_id)`, `(document_id)`, HNSW (`vector_cosine_ops`) on `embedding`, GIN on `tsv`. Embeddings are local `BAAI/bge-small-en-v1.5`, so the dimension is 384.

### questions
| Column | Type | Notes |
|---|---|---|
| id | uuid PK | |
| org_id | uuid FK | |
| question | text | |
| route | text null | direct / procedural / policy / decision / comparison; null when stopped at the groundedness gate |
| outcome | text | answered / unanswered / needs_info / review |
| answer | text | final answer shown to the visitor |
| verdicts | jsonb | evidence trail for the usage panel |
| references | jsonb | `[{file, page}]` (column name is quoted in SQL: reserved word) |
| timings_ms | jsonb | same shape as `/api/ask` `timings_ms`, so the usage panel can draw the timing strip |
| llm_usage | jsonb | `{calls, input_tokens, output_tokens, cache_read_input_tokens, models}` for cost tracking |
| latency_ms | int | end to end, including LLM retries |
| created_at | timestamptz | |

## Relations

```
organizations 1──* users
organizations 1──* assistants   (one active, others revoked)
organizations 1──* documents 1──* chunks
organizations 1──* questions
```

## Rules

- Deleting a document cascades to its chunks and removes the stored file.
- Document limit (10) is checked against `documents` rows for the org that are not `failed`.
- Usage counts come from `questions` grouped by `outcome`.
