"""Number normalization for grounding checks (docs/ai-design.md §8).

"75%" → 75, "INR 45,000" / "₹45,000" → 45000, "1,50,000" → 150000, "3.5/4.0" → 3.5 and 4.0,
"6-month" → 6. Numbers written as words ("six") are not recognised (documented limitation).
"""

import math
import re

# Grouped thousands (Western 45,000 or Indian 1,50,000) or plain digits, optional decimals.
# Not preceded by a letter/digit/dot, so "v2" and the "5" in "3.5" aren't separate numbers.
_NUMBER = re.compile(r"(?<![\w.])(?:\d{1,3}(?:,\d{2,3})*,\d{3}|\d+)(?:\.\d+)?")


def numbers_in(text: str) -> list[float]:
    return [float(m.group().replace(",", "")) for m in _NUMBER.finditer(text)]


def value_in_text(value: float, text: str) -> bool:
    return any(math.isclose(value, n, rel_tol=0, abs_tol=1e-9) for n in numbers_in(text))


def string_in_text(value: str, text: str) -> bool:
    return " ".join(value.lower().split()) in " ".join(text.lower().split())


def format_number(value: float) -> str:
    """45000.0 → '45,000'; 3.5 → '3.5'."""
    if value == int(value):
        return f"{int(value):,}"
    return f"{value:,.10f}".rstrip("0").rstrip(".")
