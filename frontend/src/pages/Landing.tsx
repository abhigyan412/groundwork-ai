// Landing (docs/frontend.md §6.1). The example on the right is the real EvidenceTrail component
// rendering static data from a real run (test question 5).
import { Link } from "react-router-dom";
import { EvidenceTrail, type Trail } from "@/components/evidence-trail/EvidenceTrail";
import { buttonClass } from "@/components/ui/button";
import { getToken } from "@/lib/auth";
import { PRODUCT_NAME } from "@/lib/brand";

const EXAMPLE: Trail = {
  route: "decision",
  outcome: "answered",
  overall: "FALSE",
  verdicts: [
    {
      id: "d1", kind: "fact", label: "Year of study 2 or above", value: "TRUE", confidence: 1, user_value: 3,
      rule: null, missing_fact: null, reason: null, detail: null,
      source: { file: "Scholarship_Rules.pdf", page: 2, excerpt: "The merit scholarship is open to students in year 2 or above." },
    },
    {
      id: "d2", kind: "fact", label: "GPA at least 3.5", value: "UNKNOWN", confidence: 0, user_value: null,
      rule: null, missing_fact: "gpa", reason: null, detail: null, source: null,
    },
    {
      id: "d3", kind: "fact", label: "No other institutional scholarship", value: "FALSE", confidence: 1,
      user_value: true, rule: null, missing_fact: null, reason: null, detail: null,
      source: { file: "Scholarship_Rules.pdf", page: 3, excerpt: "Applicants must not hold another institutional scholarship." },
    },
  ],
  timings_ms: { decisions: { d1: 2, d2: 1, d3: 3 } },
};

const STEPS = [
  { title: "Upload PDFs", body: "Add up to 10 policy documents. We read every page and keep track of where each rule lives." },
  { title: "Copy the embed code", body: "Paste one snippet on your site, or share the assistant link directly." },
  { title: "Visitors ask", body: "Answers cite the page they came from, and eligibility questions show each condition checked." },
];

export function Landing() {
  const signedIn = getToken() !== null;
  return (
    <div className="min-h-dvh bg-surface">
      <header className="border-b border-line">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-4 sm:px-8">
          <span className="text-lg font-semibold text-ink">{PRODUCT_NAME}</span>
          <nav className="flex items-center gap-2" aria-label="Account">
            {signedIn ? (
              <Link to="/app/documents" className={buttonClass({ variant: "primary", size: "sm" })}>
                Open dashboard
              </Link>
            ) : (
              <>
                <Link to="/login" className={buttonClass({ variant: "ghost", size: "sm" })}>
                  Log in
                </Link>
                <Link to="/signup" className={buttonClass({ variant: "primary", size: "sm" })}>
                  Start
                </Link>
              </>
            )}
          </nav>
        </div>
      </header>

      <main>
        <section className="mx-auto grid max-w-6xl items-start gap-12 px-4 py-16 sm:px-8 lg:grid-cols-[1fr_minmax(0,30rem)] lg:py-24">
          <div className="max-w-xl">
            <h1 className="text-2xl font-semibold text-ink">
              Turn your policy PDFs into an assistant that shows its work.
            </h1>
            <p className="mt-6 text-lg text-slate">
              Upload up to 10 documents. Get a link to embed on your site. Every answer cites the page it came
              from, and eligibility questions are checked rule by rule, not guessed.
            </p>
            <Link to="/signup" className={buttonClass({ variant: "primary", size: "lg", className: "mt-8" })}>
              Create a workspace
            </Link>
          </div>

          <figure className="rounded-panel border border-line bg-canvas p-4" aria-label="Example answer">
            <div className="ml-auto w-fit max-w-[85%] rounded-bubble bg-teal-tint px-4 py-2.5 text-sm text-ink">
              I'm in 3rd year with 82% attendance and a sports scholarship. Am I eligible for the merit scholarship?
            </div>
            <div className="mt-3 rounded-bubble border border-line bg-surface px-4 py-3 text-sm text-ink">
              No, you're not eligible: the merit scholarship can't be held with another institutional scholarship,
              such as your sports scholarship. Your year of study is fine. Your GPA wasn't checked because you
              didn't mention it.
              <p className="mt-2 font-serif text-xs text-slate">Scholarship_Rules.pdf, page 3</p>
            </div>
            <EvidenceTrail trail={EXAMPLE} className="mt-3" />
          </figure>
        </section>

        <section className="border-t border-line bg-canvas">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:px-8">
            <h2 className="text-lg font-semibold text-ink">How it works</h2>
            {/* A genuine sequence, so numbering is appropriate here. */}
            <ol className="mt-8 grid gap-8 sm:grid-cols-3">
              {STEPS.map((s, i) => (
                <li key={s.title}>
                  <span className="tabular text-sm font-semibold text-teal">{i + 1}</span>
                  <h3 className="mt-1 text-base font-semibold text-ink">{s.title}</h3>
                  <p className="mt-2 text-sm text-slate">{s.body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto max-w-6xl px-4 py-6 text-sm text-slate sm:px-8">{PRODUCT_NAME}</div>
      </footer>
    </div>
  );
}
