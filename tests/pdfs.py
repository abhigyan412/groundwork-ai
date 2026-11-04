"""Build small PDFs in memory for tests."""

import pymupdf


def make_pdf(pages: list[str], *, password: str | None = None) -> bytes:
    """One page per string; an empty string makes a page with no text."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=11)
    kwargs = {}
    if password:
        kwargs = {
            "encryption": pymupdf.PDF_ENCRYPT_AES_256,
            "user_pw": password,
            "owner_pw": password,
        }
    data = doc.tobytes(**kwargs)
    doc.close()
    return data


def simple_pdf(n_pages: int = 2, topic: str = "hostel") -> bytes:
    return make_pdf(
        [f"Page {i + 1} of the {topic} policy. Curfew is 22:00." for i in range(n_pages)]
    )
