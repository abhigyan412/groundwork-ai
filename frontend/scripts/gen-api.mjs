// Generate TypeScript types from the backend's OpenAPI schema (CLAUDE.md: never hand-write
// response types). Run `python scripts/export_openapi.py` in the repo root first.
import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";

if (!existsSync("openapi.json")) {
  console.error("openapi.json missing: run `python scripts/export_openapi.py` in the repo root.");
  process.exit(1);
}
execFileSync(
  process.platform === "win32" ? "npx.cmd" : "npx",
  ["openapi-typescript", "openapi.json", "-o", "src/lib/api-schema.d.ts"],
  { stdio: "inherit", shell: process.platform === "win32" },
);
