"""Salary and employment-type inference for Greenhouse jobs."""
import re

_AMT = r"(\d{2,3}(?:,\d{3})+|\d{2,3}(?:\.\d+)?\s?[kK])"
PAY_RE = re.compile(r"\$\s?" + _AMT + r"\s*(?:USD)?\s*(?:-|–|—|to|and)\s*\$?\s?" + _AMT)


def _num(s):
    s = s.replace(",", "").replace(" ", "").lower()
    return float(s[:-1]) * 1000 if s.endswith("k") else float(s)


def parse_salary(pay_ranges, text):
    """Annual USD (low, high) from structured pay ranges, else from '$120,000 - $180,000' text; None if absent."""
    pairs = []
    for r in pay_ranges or []:
        if r.get("currency_type") == "USD" and r.get("min_cents"):
            lo = r["min_cents"] / 100
            pairs.append((lo, (r.get("max_cents") or r["min_cents"]) / 100))
    if not pairs:
        pairs = [(_num(a), _num(b)) for a, b in PAY_RE.findall(text or "")]
    pairs = [(lo, hi) for lo, hi in pairs if 30_000 <= lo <= hi <= 2_000_000]
    if not pairs:
        return None
    return min(p[0] for p in pairs), max(p[1] for p in pairs)


def employment_type(title, text):
    """full_time | part_time | contract | intern, inferred from title first, then text."""
    t = title.lower()
    if re.search(r"\bintern(ship)?\b", t):
        return "intern"
    if re.search(r"\b(contract|contractor|temporary|temp)\b", t):
        return "contract"
    if re.search(r"\bpart[- ]time\b", t):
        return "part_time"
    low = (text or "").lower()
    if re.search(r"\bpart[- ]time\b", low) and not re.search(r"\bfull[- ]time\b", low):
        return "part_time"
    return "full_time"
