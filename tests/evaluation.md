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
| 3 | Uni | Can I hold the merit scholarship and a sports scholarship together? | Policy | NLI Boolean: FALSE |
| 4 | Uni | I'm in 2nd year, GPA 3.6, 80% attendance, no other scholarship. Am I eligible for merit? | Multi-condition, multiple decisions | ALL TRUE → eligible |
| 5 | Uni | I'm in 3rd year with 82% attendance and a sports scholarship. Am I eligible? | Multi-condition, missing fact | FALSE (other scholarship); GPA UNKNOWN noted |
| 6 | Uni | Which hostel block is cheaper, A or B? | Comparison | Numeric Choice |
| 7 | Uni | What's on the canteen menu this week? | Not in KB | Gate → unanswered |
| 8 | Co | How many sick leaves do I get per year? | Direct | Answer + Leave_Policy page |
| 9 | Co | How do I file a travel reimbursement claim? | Procedural | Ordered steps + page |
| 10 | Co | I joined 8 months ago. Can I work from home 3 days a week? | Multi-condition | Probation TRUE, days FALSE → not allowed |
| 11 | Co | Can unused casual leave be carried forward? | Policy | NLI Boolean per document |
| 12 | Co | Is the hotel cap higher for metro or non-metro cities? | Comparison | Numeric Choice |
| 13 | Co | What is the employee stock option policy? | Not in KB | Gate → unanswered |
| 14 | Co | What is the merit scholarship GPA requirement? | Isolation | Gate → unanswered (uni data not used) |

For each run, record: route taken, verdicts, outcome, references, and whether it matched the expectation.

## Isolation tests (pytest)

- [ ] Org A's token asks about content only in org B's documents → unanswered
- [ ] Org A's JWT deletes org B's document → 404
- [ ] Org A's JWT lists documents → only its own
- [ ] Assistant token on admin routes → 401
- [ ] Revoked token on `/api/ask` → 401
- [ ] Retrieval for org A never returns chunks with org B's `org_id`

## Unit tests

- [ ] Combiner: all ALL/ANY combinations of TRUE/FALSE/UNKNOWN
- [ ] Validator: unretrieved chunk, threshold not in chunk text, unknown fact, bad op
- [ ] Executors: numeric comparisons, missing fact → UNKNOWN, timeout → UNKNOWN
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
