"""Write the backend's OpenAPI schema to frontend/openapi.json (input for `npm run gen:api`).

    python scripts/export_openapi.py

Builds the app object without running its lifespan: no database, models or LLM are touched.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Placeholders so Settings validates when no .env exists (e.g. CI); never used for anything.
os.environ.setdefault("DATABASE_URL", "postgresql://unused")
os.environ.setdefault("JWT_SECRET", "x" * 48)
os.environ.setdefault("ASSISTANT_TOKEN_KEY", "unused")

from app.main import create_app  # noqa: E402

out = ROOT / "frontend" / "openapi.json"
out.write_text(json.dumps(create_app().openapi(), indent=2) + "\n", encoding="utf-8")
print(f"wrote {out.relative_to(ROOT)}")
