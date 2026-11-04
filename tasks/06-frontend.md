# Task 06: Frontend

**Day 2 (afternoon) – Day 3 (morning)** · Refs: `docs/frontend.md`, `docs/api-contracts.md`, ADR 0006

## Goal
A polished React app: landing page, auth, dashboard (documents, assistant, usage) and the embeddable widget with the evidence trail.

## Checklist

### Setup
- [ ] Vite + React + TypeScript in `frontend/`
- [ ] Tailwind with tokens from `docs/frontend.md` §4; Plex Sans/Serif via `@fontsource`
- [ ] shadcn/ui primitives restyled to tokens
- [ ] React Router, TanStack Query, react-hook-form + zod
- [ ] `api.ts` client + OpenAPI-generated types
- [ ] Vite dev proxy for `/api` and `/auth`

### Signature component
- [ ] `EvidenceTrail`: verdict rows, serif excerpts and references, parallel timing strip, plain-language route label
- [ ] Works collapsed (widget) and expanded (landing, usage panel)

### Pages
- [ ] Landing with live example (static data, real component)
- [ ] Sign up / log in with field and server errors
- [ ] App shell with sidebar, org name, log out, responsive collapse
- [ ] Documents: drop zone, client-side checks, table, limits meter, status polling, replace, delete confirm, empty state
- [ ] Assistant: link, copy, open, embed code, live preview iframe, reset with confirm
- [ ] Usage: counts row, recent questions, side panel with evidence trail

### Widget
- [ ] `/a/:token` lazy-loaded route, own layout
- [ ] Suggested questions, chat log, typing indicator, slow-response status line
- [ ] States: answered, needs info, not in documents, error with retry, inactive link
- [ ] References as `filename, page N` in serif

### Delivery
- [ ] nginx `web` service in Docker Compose serving the build and proxying the API
- [ ] Framing headers: `/a/*` frameable, everything else not
- [ ] `demo/university.html` and `demo/company.html` embedding the widget
- [ ] JS embed (last item): `embed.js` adds a floating chat button that opens the widget iframe; snippet shown on the Assistant page as a secondary option under the iframe code

### Quality floor
- [ ] Every data view has loading, empty and error states (`docs/frontend.md` §7)
- [ ] Focus rings, keyboard support, `aria-live` chat log, reduced motion
- [ ] Checked at 320 px (widget), 768 px and 1280 px (dashboard)

## Done when
A new user can sign up, upload, copy the embed code, open a demo page, ask a decision question, and expand the evidence trail, all without touching the API directly.
