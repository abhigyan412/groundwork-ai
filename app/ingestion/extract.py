"""Page-level text extraction with PyMuPDF. OCR is out of scope: pages without text are flagged.

Text is read block by block (PyMuPDF's paragraph-level grouping), so a paragraph, list item or
table row comes out as one line, not broken at the PDF's visual line wraps. Each line is
NFKC-normalized, which turns ligature glyphs such as "ﬃ" back into plain letters ("ffi"), so
keyword search and NLI see ordinary words.
"""

import unicodedata
from dataclasses import dataclass

import pymupdf

# Default block flags, plus joining words hyphenated across line ends.
_FLAGS = pymupdf.TEXTFLAGS_BLOCKS | pymupdf.TEXT_DEHYPHENATE
_TEXT_BLOCK = 0  # block type 1 is an image


@dataclass(frozen=True)
class PageText:
    page: int  # 1-based
    text: str


def clean_block(text: str) -> str:
    """One block → one line: NFKC-normalize and collapse all whitespace, line breaks included."""
    return " ".join(unicodedata.normalize("NFKC", text).split())


def _page_text(page: pymupdf.Page) -> str:
    lines = (
        clean_block(block[4])
        for block in page.get_text("blocks", flags=_FLAGS, sort=True)
        if block[6] == _TEXT_BLOCK
    )
    return "\n".join(line for line in lines if line)


def extract_pages(data: bytes) -> list[PageText]:
    """Return text per page, one line per block (empty string for pages without text).

    CPU-bound: call via asyncio.to_thread.
    """
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        return [PageText(page=i + 1, text=_page_text(page)) for i, page in enumerate(doc)]
