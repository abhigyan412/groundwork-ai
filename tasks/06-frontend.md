# Task 06: Frontend

**Day 2 (afternoon) – Day 3 (morning)** · Refs: `docs/frontend.md`, `docs/api-contracts.md`, ADR 0006

## Goal
A polished React app: landing page, auth, dashboard (documents, assistant, usage) and the embeddable widget with the evidence trail.

## Checklist

### Setup
- [x] Vite + React + TypeScript in `frontend/`
- [x] Tailwind with tokens from `docs/frontend.md` §4; Plex Sans/Serif via `@fontsource`
- [x] shadcn/ui primitives restyled to tokens
- [x] React Router, TanStack Query, react-hook-form + zod
- [x] `api.ts` client + OpenAPI-generated types
- [x] Vite dev proxy for `/api` and `/auth`

### Signature component
- [x] `EvidenceTrail`: verdict rows, serif excerpts and references, parallel timing strip, plain-language route label
- [x] Works collapsed (widget) and expanded (landing, usage panel)

### Pages
- [x] Landing with live example (static data, real component)
- [x] Sign up / log in with field and server errors
- [x] App shell with sidebar, org name, log out, responsive collapse
- [x] Documents: drop zone, client-side checks, table, limits meter, status polling, replace, delete confirm, empty state
- [x] Assistant: link, copy, open, embed code, live preview iframe, reset with confirm
- [x] Usage: counts row, recent questions, side panel with evidence trail

### Widget
- [x] `/a/:token` lazy-loaded route, own layout
- [x] Suggested questions, chat log, typing indicator, slow-response status line
- [x] States: answered, needs info, not in documents, error with retry, inactive link
- [x] References as `filename, page N` in serif

### Delivery
- [x] nginx `web` service in Docker Compose serving the build and proxying the API
- [x] Framing headers: `/a/*` frameable, everything else not
- [x] `demo/university.html` and `demo/company.html` embedding the widget
- [x] JS embed (last item): `embed.js` adds a floating chat button that opens the widget iframe; snippet shown on the Assistant page as a secondary option under the iframe code

### Quality floor
- [x] Every data view has loading, empty and error states (`docs/frontend.md` §7)
- [x] Focus rings, keyboard support, `aria-live` chat log, reduced motion
- [x] Checked at 320 px (widget), 768 px and 1280 px (dashboard)

## Done when
A new user can sign up, upload, copy the embed code, open a demo page, ask a decision question, and expand the evidence trail, all without touching the API directly.

## Notes
- **Stack:** Vite 8, React 19, TypeScript 5.9 strict (TS 7 lacks the JS API `openapi-typescript` needs), Tailwind 4 with the §4 tokens in `@theme` (default palette removed), Radix primitives restyled.
- **API types:** generated from the backend's OpenAPI schema (`scripts/export_openapi.py` → `npm run gen:api`) and committed.
- **Bundles:** every page group is lazy-loaded. The widget chunk imports only the public client, the evidence trail and UI primitives (checked in the build output); Dialog and DropdownMenu stay out of the entry chunk.
- **nginx:** only `/a/*` is frameable; everything else sends `frame-ancestors 'none'` and `X-Frame-Options: DENY`. `/a/*` sends `Referrer-Policy: no-referrer`, so the token stays out of Referer. `client_max_body_size 11m`, so FastAPI's specific 413 message reaches the user.
- **Backend changes made for the UI:**
  - `questions.overall` is stored and returned, so the Usage page shows Eligible / Not eligible without guessing.
  - Suggested questions come from section headings and are offered only if they pass the strict gate (the filename-based ones were refused by the assistant itself).
  - The offline fake LLM's extractive answer counts shared words, not Jaccard.
- **JS embed** (`public/embed.js`): Shadow DOM; the iframe loads on first open; Esc closes it, including from inside the widget via a data-free `postMessage`. Demo: `demo/js-embed.html`.
- **Verified in a real browser (Playwright, headless Chromium): 25/25 checks.** These cover:
  - the full flow without touching the API (sign up → upload → copy embed → demo page on another origin → ask → expand the evidence trail)
  - upload errors, status polling, the reset link → "no longer active"
  - widget states, 320 px and 767 px layouts
  - the dashboard refusing to load in a foreign iframe (CSP violation)
  - keyboard-only sign up, upload, copy code and ask
  - suggestions being answerable, the JS embed opening and closing, and no JS errors
