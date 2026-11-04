"""Unit tests for chunking, filename cleaning and the fake embedder."""

import itertools

import numpy as np
import pytest

from app.ingestion.chunk import chunk_text
from app.ingestion.validate import clean_filename
from app.ml.embedder import FakeEmbedder


def words(text: str) -> int:
    return len(text.split())


def test_short_page_is_one_chunk_with_lines_kept():
    text = "How to apply:\n1. Fill in form A.\n2. Attach transcripts.\n3. Submit by 30 June."
    assert chunk_text(text, words, 450, 50) == [text]


def test_chunks_respect_budget_and_overlap():
    lines = [f"Rule {i} applies to every student in block {i}." for i in range(60)]
    chunks = chunk_text("\n".join(lines), words, target_tokens=40, overlap_tokens=10)
    assert len(chunks) > 1
    assert all(words(c) <= 40 for c in chunks)
    # Each chunk after the first starts with the last line of the previous one (overlap).
    for prev, nxt in itertools.pairwise(chunks):
        assert nxt.split("\n")[0] == prev.split("\n")[-1]
    # Nothing is lost: every line appears in some chunk, in order.
    joined = "\n".join(chunks)
    positions = [joined.index(line) for line in lines]
    assert positions == sorted(positions)


def test_oversized_line_is_split_into_sentences_then_words():
    long_sentence = " ".join(["word"] * 120) + "."
    text = "Short first sentence. " + long_sentence
    chunks = chunk_text(text, words, target_tokens=50, overlap_tokens=0)
    assert all(words(c) <= 50 for c in chunks)
    assert sum(words(c) for c in chunks) == words(text)


def test_empty_text_gives_no_chunks():
    assert chunk_text("", words, 450, 50) == []
    assert chunk_text("\n\n  \n", words, 450, 50) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Scholarship_Rules.pdf", "Scholarship_Rules.pdf"),
        ("../../etc/passwd.pdf", "passwd.pdf"),
        ("C:\\Users\\me\\Policy.pdf", "Policy.pdf"),
        ("bad\x00name<>.pdf", "badname.pdf"),
        ("   ", "document.pdf"),
        (None, "document.pdf"),
        ("a" * 300 + ".pdf", "a" * 196 + ".pdf"),
    ],
)
def test_clean_filename(raw, expected):
    assert clean_filename(raw) == expected


def test_fake_embedder_is_deterministic_normalized_and_similarity_aware():
    e = FakeEmbedder(384)
    a, b, c = e.embed_passages(
        ["hostel curfew time", "what time is the hostel curfew", "sick leave days"]
    )
    assert a.shape == (384,)
    assert np.isclose(np.linalg.norm(a), 1.0)
    assert np.array_equal(a, e.embed_query("hostel curfew time"))
    assert float(a @ b) > float(a @ c)


def test_clean_block_fixes_ligatures_and_whitespace():
    from app.ingestion.extract import clean_block

    ffi = chr(0xFB03)  # the single-glyph "ffi" ligature PDFs often contain
    nbsp = chr(0xA0)
    raw = (
        "Upload your o"
        + ffi
        + "cial"
        + chr(9)
        + "transcript"
        + nbsp
        + nbsp
        + "by"
        + chr(10)
        + "30 June."
    )
    assert clean_block(raw) == "Upload your official transcript by 30 June."


def test_extract_pages_joins_wrapped_lines_and_keeps_blocks_apart():
    from app.ingestion.extract import extract_pages
    from tests.pdfs import make_pdf

    long_para = "Applicants must hold a cumulative GPA of at least 3.5 on a 4.0 scale, " * 3
    data = make_pdf([long_para.strip()])  # wraps across several visual lines in the PDF
    (page,) = extract_pages(data)
    assert page.page == 1
    assert page.text == " ".join(long_para.split())  # one line, no mid-sentence breaks
