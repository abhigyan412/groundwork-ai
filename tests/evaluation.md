# Evaluation

How we prove the system works: test data, test questions, isolation tests, and unit tests.

## Test data [Proposed]

Self-written PDFs with deliberately clean, testable rules.

**Org 1: Riverside University**
- `Scholarship_Rules.pdf`: merit scholarship requires year ≥ 2, GPA ≥ 3.5/4.0, attendance ≥ 75%, no other institutional scholarship; application steps.
- `Hostel_Policy.pdf`: curfew, fees for Block A and Block B, guest rules.
- `Exam_Regulations.pdf`: re-evaluation process, minimum attendance for exams.

**Org 2: Northwind Technologies**
- `Leave_Policy.pdf`: casual/sick/earned leave counts, carry-forward rules.
- `Travel_Policy.pdf`: hotel caps (metro vs non-metro), claim process, approvals.
- `WFH_Policy.pdf`: eligible after 6-month probation, max 2 days/week, manager approval.

## Test questions

| # | Org | Question | Type | Expected |
|---|---|---|---|---|
| 1 | Uni | What time is the hostel curfew? | Direct | Answer + Hostel_Policy page |
| 2 | Uni | How do I apply for the merit scholarship? | Procedural | Ordered steps + page |
| 3 | Uni | Can I hold the merit scholarship and a sports scholarship together? | Policy | Pattern → "It is permitted to hold the merit scholarship and a sports scholarship together." → contradiction on top-3 chunk → FALSE |
| 4 | Uni | I'm in 2nd year, GPA 3.6, 80% attendance, no other scholarship. Am I eligible for merit? | Multi-condition, multiple decisions | 4 fact checks, all rule-grounded: `year >= 2`, `gpa >= 3.5`, `attendance_pct >= 75`, `has_other_scholarship == false` → ALL TRUE → eligible |
| 5 | Uni | I'm in 3rd year with 82% attendance and a sports scholarship. Am I eligible? | Multi-condition, missing fact | `has_other_scholarship == false` FALSE; `gpa` UNKNOWN (missing) → ALL FALSE, outcome `answered`, answer notes GPA wasn't given |
| 6 | Uni | Which hostel block is cheaper, A or B? | Comparison | `{options: [Block A, Block B], criterion: hostel fee, better: lower}` → values extracted and found in chunks → code picks the lower |
| 7 | Uni | What's on the canteen menu this week? | Not in KB | Gate → unanswered |
| 8 | Co | How many sick leaves do I get per year? | Direct | Answer + Leave_Policy page |
| 9 | Co | How do I file a travel reimbursement claim? | Procedural | Ordered steps + page |
| 10 | Co | I joined 8 months ago. Can I work from home 3 days a week? | Multi-condition | `tenure_months >= 6` TRUE; `wfh_days_per_week <= 2` FALSE; manager approval UNKNOWN (missing) → ALL FALSE → not allowed |
| 11 | Co | Can unused casual leave be carried forward? | Policy | Pattern "Can X be Y?" → "Unused casual leave can be carried forward." → NLI on top 3 chunks → verdict per Leave_Policy text |
| 12 | Co | Is the hotel cap higher for metro or non-metro cities? | Comparison | `{options: [metro, non-metro], criterion: hotel cap, better: higher}` → code picks metro |
| 13 | Co | What is the employee stock option policy? | Not in KB | Gate → unanswered |
| 14 | Co | What is the merit scholarship GPA requirement? | Isolation | Gate → unanswered (uni data not used) |

| 15 | Uni | Does the hostel have a gym, and when is it open? | Not in KB (near miss) | Gate → unanswered |
| 16 | Uni | What is the fee for a supplementary exam? | Not in KB (near miss) | Gate → unanswered |
| 17 | Co | How many weeks of parental leave do employees get? | Not in KB (near miss) | Gate → unanswered |
| 18 | Co | What is the daily meal allowance on business trips? | Not in KB (near miss) | Gate → unanswered |

All 18 are in `sample_data/questions.json` with their expected sources.

For each run, record: route taken, verdicts, outcome, references, and whether it matched the expectation.

## Retrieval evaluation (`scripts/eval_retrieval.py`, real models)

Checks that each in-KB question's expected file/page appears in the top 3 reranked chunks and passes the gate, and that each not-in-KB question is stopped by the gate. It also reports the score margins and which not-in-KB questions would leak if misrouted to "decision".

Last run (task 03): **18/18**. Margins: +1.98 (strict gate), +3.74 (decision gate), +1.57 (strict gate vs the highest not-in-KB score). Q17 would leak if misrouted.

## Isolation tests (pytest)

- [ ] Org A's token asks about content only in org B's documents → unanswered
- [ ] Org A's JWT deletes org B's document → 404
- [ ] Org A's JWT lists documents → only its own
- [ ] Assistant token on admin routes → 401
- [ ] Revoked token on `/api/ask` → 401
- [ ] Retrieval for org A never returns chunks with org B's `org_id`

## Unit tests

- [ ] Combiner: all ALL/ANY combinations of TRUE/FALSE/UNKNOWN
- [ ] Validator: unretrieved chunk, value not in chunk text, fact type mismatch, op not allowed for type (e.g. `>=` on boolean)
- [ ] Number normalization: "75%", "₹45,000", "3.5/4.0", "6-month"
- [ ] Rule grounding: spec dropped when the cited chunk doesn't entail `rule` (stub NLI)
- [ ] Policy patterns: each pattern in `docs/ai-design.md` §5 → expected hypothesis; non-matching question → decision path
- [ ] Comparison: lower/higher pick, missing value, tie, unit mismatch, value not in chunk → dropped, no numbers → NLI fallback
- [ ] Executors: number/boolean/string comparisons, missing fact → UNKNOWN, timeout → UNKNOWN
- [ ] Outcome: overall UNKNOWN from missing facts → `needs_info`; decided result with missing facts → `answered`; model failure → `review`
- [ ] Upload limits: non-PDF, > 10 MB, > 20 pages, 11th document
- [ ] Empty question → 400

## UI checks (manual, before recording the demo)

- [ ] Full flow without touching the API: sign up → upload → copy embed → open demo page → ask → expand evidence trail
- [ ] Upload errors shown per file: non-PDF, > 10 MB, > 20 pages, 11th document
- [ ] Document status moves from processing to ready without a page refresh
- [ ] Reset link: old embed shows "This assistant link is no longer active"
- [ ] Widget states: answered, needs info, not in documents, error with retry
- [ ] Dashboard route cannot be loaded inside an iframe
- [ ] Widget usable at 320 px; dashboard usable at 768 px
- [ ] Keyboard-only: sign up, upload, copy code, ask a question
