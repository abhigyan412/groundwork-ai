# Requirements

What the product must do, condensed from the assignment brief.

## Product

- Multi-tenant SaaS: each organization has its own isolated knowledge base and assistant.
- One organization's information must never be used to answer another organization's questions.

## Organization account

- Register, log in, log out, see a dashboard.
- Manage the knowledge base; generate and regenerate the assistant URL; copy embed code.
- Simple but functional authentication is enough.

## Knowledge base

- Upload PDFs as the knowledge base.
- **Limits:** max 10 PDFs per organization, max 20 pages per PDF, max 10 MB per PDF. Validate and return meaningful errors.
- View documents with basic info, delete documents, upload replacements within limits.
- Process documents for retrieval; keep enough metadata to cite the source document and page.

## Assistant

- Unique assistant URL per organization.
- The token identifies the assistant without exposing credentials or document contents.
- Works for visitors without login.
- Embeddable via iframe or JavaScript; dashboard provides the embed code.

## Visitor experience

- Simple chat interface, no account needed.
- Answers grounded in the org's knowledge base, with references like `Scholarship_Rules.pdf — Page 4`.

## AI behavior

- Pipeline: question → organization identification → retrieval → understanding → decision/reasoning → answer generation → answer + references.
- LLM understands/decomposes questions and generates answers.
- System 1 models make specific structured decisions; independent decisions may run in parallel.
- Application logic combines decisions into an overall result.
- At least two decision types (Choice, Boolean, Score, Classification).
- Must **not** be a single "question → LLM → answer" prompt.
- If the knowledge base lacks the information, say so; never invent an answer.

## Question coverage

Direct information, policy, procedural, multi-condition decision, comparison, and not-in-knowledge-base questions.

## API and security

- `POST /api/ask`-style endpoint with assistant token and question.
- Validate token server-side; identify the org; retrieve only that org's knowledge.
- Admin APIs require authentication; assistant token cannot access the dashboard.
- Private documents never publicly exposed.
- Isolation explicitly tested.

## Dashboard

- Account: organization name, login/logout.
- Knowledge base: documents, limits, upload/delete.
- Assistant: URL, regenerate token, copy embed code.
- Usage (encouraged): questions asked, answered, unable to answer / human review.

## Error handling

Invalid PDF, size/page/document limits, invalid token, empty question, no relevant knowledge, LLM/API failure, decision-model failure, document-processing failure.

## Submission

- GitHub repo: source, example env file, schema setup, sample data, README, no secrets.
- Working end-to-end flow (deployment optional).
- Demo video, 8–15 min: product walkthrough, architecture, AI decision flow with a multi-decision question, multi-tenant isolation with 2+ orgs.
- Test data: 2+ orgs, 2–3 PDFs each, 10+ questions, 2+ multi-condition, 1+ with multiple structured decisions, 1+ not in the knowledge base.
- Timeline: 2–3 days.

## Evaluation weights

| Area | Weight |
|---|---|
| Product & UX | 20% |
| AI architecture | 30% |
| Question decomposition & decision making | 25% |
| Knowledge grounding & accuracy | 15% |
| Engineering quality | 10% |
