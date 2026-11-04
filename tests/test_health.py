async def test_health_ok(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": "ok"}


async def test_schema_has_all_tables_and_vector(client, db):  # client applies the schema
    tables = {
        r["table_name"]
        for r in await db.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    }
    assert {"organizations", "users", "assistants", "documents", "chunks", "questions"} <= tables
    assert await db.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'") == 1
    dim = await db.fetchval(
        "SELECT atttypmod FROM pg_attribute "
        "WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'"
    )
    assert dim == 384
