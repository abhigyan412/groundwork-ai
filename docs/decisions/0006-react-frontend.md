# 0006: React frontend with a commercial SaaS look

**Status:** Accepted

## Context
Product & UX is 20% of the grade, and the goal is an MVP that looks like a real business product. Server-rendered templates would be faster to build but harder to make feel polished.

## Decision
A separate React (Vite + TypeScript) app for the landing page, dashboard and widget, styled with Tailwind and restyled shadcn/ui primitives. Served by nginx, which also proxies the API so everything shares one origin.

## Consequences
- More polished, interactive dashboard (live widget preview, upload status polling, evidence trail).
- About half a day of extra work; frontend gets its own task file.
- Same-origin proxy avoids CORS; the widget route alone allows framing.
- OpenAPI-generated types keep the frontend in sync with backend contracts.
