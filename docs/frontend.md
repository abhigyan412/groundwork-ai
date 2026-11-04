# Frontend

React app for the organization dashboard, a small public landing page, and the embeddable chat widget. The goal is a modern commercial SaaS feel: calm, precise, and trustworthy, because the product's promise is "answers you can check."

> Status: React [Confirmed] · everything else here [Proposed]

---

## 1. Product framing

| | |
|---|---|
| Working name | **Groundwork** (placeholder, easy to rename in one constant) [Open] |
| Who uses the dashboard | Ops, HR, admissions or policy owners at an organization. Not engineers. |
| Who uses the widget | Students, employees, customers asking about policies. First-time, no login. |
| Dashboard's job | Upload documents, get an assistant link, trust that it's working. |
| Widget's job | Give an answer the visitor can check, with the exact page it came from. |

Everything visual should support one idea: **every answer shows its evidence.**

---

## 2. Stack

| Concern | Choice |
|---|---|
| Build | Vite + React 18 + TypeScript |
| Styling | Tailwind CSS with the tokens in §4 (no default Tailwind palette in components) |
| Components | shadcn/ui primitives (Dialog, DropdownMenu, Tooltip, Tabs, Toast via sonner), restyled with our tokens |
| Routing | React Router |
| Server state | TanStack Query (polling for document status) |
| Forms | react-hook-form + zod |
| Icons | lucide-react, 16/20 px, stroke 1.75 |
| Fonts | IBM Plex Sans, IBM Plex Serif (self-hosted via `@fontsource`) |

---

## 3. Routes

| Route | Page | Auth |
|---|---|---|
| `/` | Landing | Public |
| `/signup` | Create workspace | Public |
| `/login` | Log in | Public |
| `/app/documents` | Knowledge base | JWT |
| `/app/assistant` | Assistant link, embed code, live preview | JWT |
| `/app/usage` | Usage counts + recent questions | JWT |
| `/a/:token` | Chat widget (iframe target) | Assistant token |

- `/a/:token` is a separate lazy-loaded route with its own minimal layout, so the widget bundle never includes dashboard code.
- Unauthenticated access to `/app/*` redirects to `/login`.

---

## 4. Design tokens

### Color

| Token | Hex | Use |
|---|---|---|
| `ink` | `#16202E` | Primary text, primary buttons |
| `slate` | `#5A6577` | Secondary text, icons |
| `line` | `#DDE2E8` | Borders, dividers |
| `canvas` | `#F5F7F9` | App background |
| `surface` | `#FFFFFF` | Panels, chat bubbles |
| `teal` | `#0F6B66` | Links, focus ring, selected nav, accent actions |
| `teal-tint` | `#E3F1EF` | Selected states, user chat bubble |

Verdict colors (used only for decision results, nowhere else):

| Verdict | Text | Tint | Label |
|---|---|---|---|
| TRUE | `#2E7D4F` | `#E6F2EA` | Met |
| FALSE | `#B3412F` | `#F7E6E2` | Not met |
| UNKNOWN | `#A86F12` | `#F7EED9` | Need info |

Light mode only for the MVP; dark mode listed under production improvements.

### Typography

- **IBM Plex Sans** for all interface text.
- **IBM Plex Serif** only for text that comes from the organization's documents: quoted excerpts and source references. Serif means "this is from your document." That rule carries meaning; don't use serif decoratively.
- Scale (px): 13 / 14 / 16 / 20 / 28 / 40. Body 15–16, line-height 1.55. Max line length ~70 characters in chat and prose.
- Weights: 400 and 600 only. Tabular numbers for counts, sizes and timings.
- Sentence case everywhere. No all-caps labels.

### Shape and space

- Radius by role, not one value everywhere: controls 6 px, panels 10 px, chat bubbles 14 px, verdict chips 4 px.
- Borders over shadows. One subtle shadow only on floating elements (dialogs, menus, the widget launcher).
- Spacing on a 4 px grid; generous whitespace in the dashboard, tighter in the widget.

### Avoid

Identical card grids, gradient washes, eyebrow labels above headings, arrows appended to button text, decorative motion on page load, dividers or numbering that don't encode real structure.

---

## 5. Signature component: the evidence trail

The one place the design spends its boldness. It appears in three places: under each widget answer (collapsed by default), in the landing hero (expanded, as a live example), and in the usage page's question detail.

```
┌──────────────────────────────────────────────────────────────┐
│ How this was answered                         Decision check │
│                                                              │
│  Met        GPA at least 3.5                     you: 3.6    │
│             "Applicants must hold a cumulative GPA of 3.5…"  │  ← serif excerpt
│             Scholarship_Rules.pdf, page 4                    │  ← serif reference
│                                                              │
│  Met        Year of study 2 or above             you: 2      │
│  Not met    Can't combine with another scholarship           │
│             "The merit award may not be held together…"      │
│             Scholarship_Rules.pdf, page 6                    │
│                                                              │
│  Checks ran in parallel                                      │
│  GPA       ▏                                    1 ms         │
│  Year      ▏                                    1 ms         │
│  Combine   ████████████████                     140 ms       │
│                                                              │
│  Result: not eligible (all conditions must be met)           │
└──────────────────────────────────────────────────────────────┘
```

Rules:
- Each verdict row: verdict chip, plain-language condition, the user's value if any, excerpt in serif, reference in serif.
- The timing strip draws each decision as a bar starting at the same x position, so parallel execution is visible at a glance.
- The route is shown in plain words: "Direct answer", "Policy check", "Comparison", "Decision check".
- Never show raw JSON, prompts, model names or confidence decimals to visitors. Confidence appears only as a tooltip ("High confidence").

---

## 6. Pages

### 6.1 Landing `/`

```
┌───────────────────────────────────────────────────────────────┐
│ Groundwork                                  Log in  [Start]   │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│  Turn your policy PDFs into an     ┌─────────────────────────┐│
│  assistant that shows its work.    │ Visitor: Am I eligible  ││
│                                    │ for the merit…?         ││
│  Upload up to 10 documents. Get a  │ Answer…                 ││
│  link to embed on your site. Every │ [evidence trail,        ││
│  answer cites the page it came     │  expanded]              ││
│  from.                             └─────────────────────────┘│
│  [Create a workspace]                                         │
│                                                               │
│  How it works                                                 │
│  1 Upload PDFs   2 Copy the embed code   3 Visitors ask       │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

- Left-aligned headline, real example on the right (static data, rendered with the real evidence-trail component).
- "How it works" is genuinely a sequence, so numbering is appropriate here.
- One page only. No pricing, testimonials or feature grids.

### 6.2 Sign up / log in

- Centered single form, product name above. Sign up asks for organization name, email, password.
- Field-level errors from zod; server errors in one line under the button ("That email already has a workspace. Log in instead.").

### 6.3 App shell

```
┌────────────┬──────────────────────────────────────────────────┐
│ Groundwork │  Page title                       [page action]  │
│            │                                                  │
│ Documents  │                                                  │
│ Assistant  │                 page content                     │
│ Usage      │                                                  │
│            │                                                  │
│ ────────── │                                                  │
│ Riverside  │                                                  │
│ University │                                                  │
│ Log out    │                                                  │
└────────────┴──────────────────────────────────────────────────┘
```

- Left sidebar 232 px, collapses to a top bar under 768 px.
- Organization name and log out at the bottom of the sidebar.

### 6.4 Documents `/app/documents`

```
 Documents                                        [Upload PDF]
 4 of 10 documents used  ▓▓▓▓░░░░░░   PDFs up to 20 pages, 10 MB

 ┌──────────────────────────────────────────────────────────────┐
 │  Drop PDFs here or browse                                    │
 └──────────────────────────────────────────────────────────────┘

 Name                     Pages   Size     Status        Added
 Scholarship_Rules.pdf    6       420 KB   Ready         2 Nov   ⋯
 Hostel_Policy.pdf        4       310 KB   Processing…   just now
 Exam_Regulations.pdf     —       —        Failed: no readable text  ⋯
```

- Drop zone validates type and size in the browser first, then shows server errors per file.
- Status polls every 2 s while any document is processing.
- Row menu: Replace, Delete. Delete opens a confirm dialog: "Delete Hostel_Policy.pdf? The assistant will stop using it immediately."
- At 10/10 the upload button is disabled with a tooltip: "Delete a document to upload another."
- Empty state: "No documents yet. Upload the PDFs your assistant should answer from."

### 6.5 Assistant `/app/assistant`

```
 Assistant

 Assistant link
 https://…/a/k3f9…            [Copy link]   [Open]

 Embed on your site
 ┌───────────────────────────────────────────────┐
 │ <iframe src="…" width="400" height="600" …>   │ [Copy code]
 └───────────────────────────────────────────────┘

 Preview                       ┌──────────────┐
                               │ live widget  │
                               │ (iframe)     │
                               └──────────────┘

 Reset link
 Anyone using the old link or embed will lose access.  [Reset link]
```

- Live preview is the real widget in an iframe, so owners test before embedding.
- Reset is a destructive action with a confirm dialog; after reset, the new link and code replace the old ones and a toast says "Link reset. Update the embed code on your site."
- If no documents are ready, a notice above the preview: "Upload at least one document so the assistant has something to answer from."

### 6.6 Usage `/app/usage`

```
 Usage
 Asked 128    Answered 97    Needed info 14    Not in documents 11    For review 6

 Recent questions
 Am I eligible for the merit scholarship?   Decision check   Not eligible     2h ago
 What time is the hostel curfew?            Direct answer    Answered         3h ago
 What's on the canteen menu?                —                Not in documents 5h ago
```

- Counts as a single row of plain numbers with labels, not five identical cards.
- Clicking a recent question opens a side panel with the answer and its evidence trail.

### 6.7 Widget `/a/:token`

```
┌──────────────────────────────┐
│ Riverside University         │
│ Ask about our policies       │
├──────────────────────────────┤
│                              │
│ Try asking                   │
│ [What's the hostel curfew?]  │
│ [How do I apply for…?]       │
│                              │
│        ┌──────────────────┐  │
│        │ user question    │  │
│        └──────────────────┘  │
│ ┌──────────────────────────┐ │
│ │ answer text              │ │
│ │ Scholarship_Rules.pdf,   │ │
│ │ page 4                   │ │
│ │ How this was answered ▾  │ │
│ └──────────────────────────┘ │
├──────────────────────────────┤
│ [Ask a question…]    [Send]  │
└──────────────────────────────┘
```

- Works from 320 px wide; fills the iframe.
- Suggested questions are generic per org for the MVP (configurable later).
- Answer states:
  - **Answered:** answer + references + collapsed evidence trail.
  - **Needs info:** answer ends with the specific question ("What's your current GPA?") and the input gets focus.
  - **Not in documents:** "The documents for Riverside University don't cover this." No references.
  - **Error:** "Couldn't get an answer right now. Try again." with a retry button.
- While waiting: a typing indicator; after 4 s, a quiet status line ("Checking the documents…").
- Invalid or reset link: full-widget message "This assistant link is no longer active."

---

## 7. States checklist (every data view)

| State | Treatment |
|---|---|
| Loading | Skeleton rows matching the final layout, no spinners for page loads |
| Empty | One sentence explaining what to do + the primary action |
| Error | What failed and how to fix it, with retry; never "Something went wrong" |
| Processing | Inline status with subtle pulse on the status text only |
| Success | Toast for actions ("Document deleted", "Link copied") |

---

## 8. Copy rules

- Name things by what users understand: "assistant link", not "token"; "documents", not "knowledge base chunks".
- Buttons say exactly what happens: "Upload PDF", "Copy code", "Reset link", "Delete document".
- The same action keeps the same word through the flow (button "Reset link" → toast "Link reset").
- Errors are specific and don't apologize: "This PDF has 24 pages. The limit is 20."

---

## 9. API usage

| Screen | Endpoint |
|---|---|
| Sign up / log in | `POST /auth/register`, `POST /auth/login` |
| App shell | `GET /api/admin/me` |
| Documents | `GET/POST /api/admin/documents`, `DELETE /api/admin/documents/{id}` |
| Assistant | `GET /api/admin/assistant`, `POST /api/admin/assistant/regenerate` |
| Usage | `GET /api/admin/usage`, `GET /api/admin/questions` |
| Widget | `GET /api/public/assistant/{token}`, `POST /api/ask` |

- One `api.ts` client; attaches the JWT; on 401 clears session and redirects to `/login`.
- JWT kept in `localStorage` for the MVP (limitation noted in README; httpOnly cookie is the production choice).
- Generated TypeScript types from FastAPI's OpenAPI schema (`openapi-typescript`) so frontend and backend contracts can't drift.

---

## 10. Accessibility and quality floor

- Visible focus ring (2 px `teal`) on every interactive element.
- Verdicts never rely on color alone: chip text says "Met / Not met / Need info".
- Chat log is an `aria-live="polite"` region.
- Respect `prefers-reduced-motion`; the only motion is response to user actions (panel open, toast, row removal).
- Keyboard: Enter sends, Shift+Enter new line, Esc closes dialogs.
- Responsive from 320 px (widget) and 768 px (dashboard collapses sidebar).

---

## 11. Build and deployment

```
frontend/
  src/
    app/            # routes, layouts
    pages/          # landing, auth, documents, assistant, usage
    widget/         # widget route + chat components (lazy-loaded)
    components/
      evidence-trail/
      ui/           # restyled shadcn primitives
    lib/            # api.ts, auth, query client, generated types
    styles/         # tokens, tailwind config
  index.html
  vite.config.ts    # dev proxy /api and /auth → backend
```

- **Dev:** Vite proxies `/api` and `/auth` to FastAPI, so no CORS setup is needed.
- **Docker:** a `web` service (nginx) serves the built app and proxies `/api` and `/auth` to the backend, so frontend and API share one origin.
- **Framing headers (nginx):** `/a/*` allows framing by any site (`Content-Security-Policy: frame-ancestors *`); every other route denies it (`frame-ancestors 'none'`), so the dashboard can't be embedded.
