"""Generate the 6 sample policy PDFs used by the demo and the evaluation (tests/evaluation.md).

    python scripts/make_sample_pdfs.py            # writes sample_data/{riverside,northwind}/*.pdf

The content is fictional and deliberately clean: every rule a test question depends on is
stated once, with digits (not words), on a known page. Each list item below is one PDF page.
"""

import argparse
from pathlib import Path

import pymupdf

CSS = """
* { font-family: sans-serif; }
body { font-size: 10.5pt; line-height: 1.45; color: #16202E; }
h1 { font-size: 17pt; margin: 0 0 4pt 0; }
h2 { font-size: 12.5pt; margin: 12pt 0 4pt 0; }
p, li { margin: 0 0 5pt 0; }
.meta { color: #5A6577; font-size: 9pt; margin-bottom: 10pt; }
table { border-collapse: collapse; margin: 4pt 0 8pt 0; }
td, th { border: 1px solid #DDE2E8; padding: 3pt 8pt; text-align: left; }
"""

DOCS: dict[str, dict[str, list[str]]] = {
    "riverside": {
        "Scholarship_Rules.pdf": [
            """<h1>Riverside University: Merit Scholarship Rules</h1>
<p class="meta">Office of Student Finance · Effective 2025-26 · Version 3.2</p>
<h2>1. Purpose</h2>
<p>The Riverside Merit Scholarship recognises sustained academic achievement. It covers 50% of
tuition fees for one academic year and may be renewed annually if the student continues to meet
every eligibility condition in Section 2.</p>
<h2>2. Scope</h2>
<p>These rules apply to full-time undergraduate students enrolled at the main campus. Part-time
and exchange students are covered by separate schemes administered by the International Office.</p>
<p>Questions about these rules should be sent to the Office of Student Finance.</p>""",
            """<h1>2. Eligibility conditions</h1>
<p>A student is eligible for the merit scholarship only if all of the following conditions are met
at the time of application.</p>
<h2>2.1 Year of study</h2>
<p>The merit scholarship is open to students in year 2 or above. First-year students are not
eligible, as no university GPA is available for them yet.</p>
<h2>2.2 Academic performance</h2>
<p>Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale, as shown on the official
transcript at the end of the previous semester.</p>
<h2>2.3 Attendance</h2>
<p>Applicants must have attendance of at least 75% across all registered courses in the previous
academic year.</p>""",
            """<h1>3. Other scholarships</h1>
<h2>3.1 No combination with other awards</h2>
<p>Applicants must not hold another institutional scholarship. The merit scholarship may not be
held together with any other scholarship awarded by Riverside University, including the sports
scholarship, the arts scholarship and the need-based bursary.</p>
<h2>3.2 External awards</h2>
<p>Scholarships from external bodies (for example, government or industry awards) do not affect
eligibility, but must be declared on the application form.</p>
<h2>3.3 Withdrawal</h2>
<p>If a student accepts another institutional scholarship after receiving the merit scholarship,
the merit scholarship is withdrawn from the following semester.</p>""",
            """<h1>4. How to apply</h1>
<p>Applications open on 1 June and close on 30 June each year.</p>
<ol>
<li>Log in to the Student Portal and open the Scholarships section.</li>
<li>Complete the Merit Scholarship application form.</li>
<li>Upload your official transcript for the previous semester.</li>
<li>Upload the attendance certificate issued by your department office.</li>
<li>Declare any external scholarships you currently hold.</li>
<li>Submit the application before 30 June. Late applications are not accepted.</li>
</ol>
<p>Results are published on the Student Portal within 4 weeks of the closing date.</p>""",
        ],
        "Hostel_Policy.pdf": [
            """<h1>Riverside University: Hostel Policy</h1>
<p class="meta">Residential Services · 2025-26</p>
<h2>1. Curfew</h2>
<p>The hostel curfew is 22:00 (10 pm) from Sunday to Thursday, and 23:30 on Friday and Saturday.
Residents returning after curfew must sign the late-entry register at the front desk.</p>
<p>Three late entries in one semester lead to a meeting with the warden.</p>
<h2>2. Quiet hours</h2>
<p>Quiet hours run from 22:00 to 07:00 every day.</p>""",
            """<h1>2. Accommodation fees</h1>
<p>Fees are charged per semester and include water and electricity.</p>
<table>
<tr><th>Block</th><th>Room type</th><th>Fee per semester</th></tr>
<tr><td>Block A</td><td>Single room, attached bathroom</td><td>INR 45,000</td></tr>
<tr><td>Block B</td><td>Twin-sharing room, shared bathroom</td><td>INR 32,000</td></tr>
</table>
<p>The Block A hostel fee is INR 45,000 per semester. The Block B hostel fee is INR 32,000 per
semester.</p>
<p>A refundable security deposit of INR 5,000 is collected at check-in.</p>""",
            """<h1>3. Guests</h1>
<p>Residents may receive guests in the common lounge between 10:00 and 20:00. Guests are not
permitted in residential rooms at any time.</p>
<p>All guests must show photo identification and sign in at the front desk.</p>
<p>Overnight guests are not allowed.</p>""",
        ],
        "Exam_Regulations.pdf": [
            """<h1>Riverside University: Examination Regulations</h1>
<p class="meta">Office of the Controller of Examinations · 2025-26</p>
<h2>1. Eligibility to sit examinations</h2>
<p>Students must have a minimum attendance of 70% in a course to sit its end-semester
examination. Students below this threshold are marked as debarred for that course.</p>
<h2>2. Admit cards</h2>
<p>Admit cards are issued through the Student Portal 7 days before the first examination.</p>""",
            """<h1>3. Re-evaluation</h1>
<p>Students who are not satisfied with their marks may apply for re-evaluation.</p>
<ol>
<li>Apply through the Student Portal within 10 days of the results being published.</li>
<li>Pay the re-evaluation fee of INR 500 per course.</li>
<li>The answer script is re-marked by a different examiner.</li>
<li>Revised results are published within 21 days of the application.</li>
</ol>
<p>Marks may go up or down after re-evaluation. The re-evaluated mark is final.</p>""",
        ],
    },
    "northwind": {
        "Leave_Policy.pdf": [
            """<h1>Northwind Technologies: Leave Policy</h1>
<p class="meta">People Team · Applies to all full-time employees in India · Rev. 2025</p>
<h2>1. Annual leave entitlement</h2>
<table>
<tr><th>Leave type</th><th>Days per calendar year</th></tr>
<tr><td>Casual leave</td><td>8</td></tr>
<tr><td>Sick leave</td><td>12</td></tr>
<tr><td>Earned leave</td><td>18</td></tr>
</table>
<p>Employees get 12 days of sick leave per calendar year. Sick leave of more than 2 consecutive
days requires a medical certificate.</p>""",
            """<h1>2. Carry-forward rules</h1>
<p>Unused casual leave cannot be carried forward. Any casual leave not taken by 31 December
lapses.</p>
<p>Unused sick leave cannot be carried forward.</p>
<p>Unused earned leave can be carried forward to the next year, up to a maximum balance of 45
days. Earned leave above 45 days lapses on 31 December.</p>
<h2>3. Applying for leave</h2>
<p>Leave is applied for in the HR portal and approved by the reporting manager.</p>""",
        ],
        "Travel_Policy.pdf": [
            """<h1>Northwind Technologies: Business Travel Policy</h1>
<p class="meta">Finance · Rev. 2025</p>
<h2>1. Approval</h2>
<p>All business travel must be approved in advance by the reporting manager. Travel abroad also
requires approval from the department head.</p>
<h2>2. Hotel limits</h2>
<p>The hotel cap for metro cities is INR 7,500 per night. The hotel cap for non-metro cities is
INR 4,500 per night. Metro cities are Mumbai, Delhi, Bengaluru, Chennai, Kolkata and Hyderabad.</p>
<p>Stays above the cap need written approval from the department head.</p>""",
            """<h1>3. Claiming reimbursement</h1>
<ol>
<li>Open the Expenses app and create a new travel claim within 15 days of returning.</li>
<li>Add each expense with its date, category and amount.</li>
<li>Attach a receipt for every expense above INR 200.</li>
<li>Submit the claim for approval by your reporting manager.</li>
<li>Finance reimburses approved claims with the next monthly salary.</li>
</ol>
<p>Claims submitted after 15 days need department head approval.</p>""",
        ],
        "WFH_Policy.pdf": [
            """<h1>Northwind Technologies: Work From Home Policy</h1>
<p class="meta">People Team · Rev. 2025</p>
<h2>1. Eligibility</h2>
<p>Employees are eligible to work from home after completing the 6-month probation period.
Employees still on probation must work from the office.</p>
<h2>2. Limits</h2>
<p>Employees may work from home for a maximum of 2 days per week.</p>
<p>Work from home is not allowed on the first working Monday of each month, which is the all-hands
day.</p>""",
            """<h1>3. Approval</h1>
<p>Each work-from-home day requires prior approval from the reporting manager in the HR portal,
at least 1 working day in advance.</p>
<h2>4. Equipment and availability</h2>
<p>Employees working from home must be reachable on chat and phone during core hours, 10:00 to
16:00.</p>""",
        ],
    },
}


def build(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    # PyMuPDF's Rect + tuple adds element-wise: 56 pt margins on every side.
    rect = pymupdf.paper_rect("a4") + (56, 56, -56, -56)  # noqa: RUF005
    for html in pages:
        page = doc.new_page(width=595, height=842)
        spare, _ = page.insert_htmlbox(rect, html, css=CSS)
        if spare < 0:
            raise ValueError(f"Content overflows the page: {html[:60]}...")
    data = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("sample_data"))
    args = parser.parse_args()
    for org, docs in DOCS.items():
        for filename, pages in docs.items():
            path = args.out / org / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(build(pages))
            print(f"{path}  ({len(pages)} pages)")


if __name__ == "__main__":
    main()
