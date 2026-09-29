"""Text utilities: chunking, tokenising and keyword weighting."""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS = set("""
a about above after again against all also am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her here
hers him his how i if in into is it its itself just me more most my no nor not now of off on once only or other
our ours out over own same she should so some such than that the their theirs them then there these they this
those through to too under until up very was we were what when where which while who whom why will with would
you your yours page slide notes one two three new use used using may might must shall will also etc via per
""".split())

_WORD = re.compile(r"[^\W\d_][\w\-]{2,}")            # 3+ chars, any language (Zürich, São)
_QUERY_WORD = re.compile(r"[^\W_][\w\-&+.]*")          # queries also keep short terms: AI, HR, Q3, M&A
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
MDLINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")


def tokenize(text: str) -> list[str]:
    return [w for w in (m.group(0).lower().strip("-") for m in _WORD.finditer(text)) if w not in STOPWORDS]


def query_terms(query: str) -> list[str]:
    """Search terms from a user query: like tokenize(), but short words (AI, HR, Q3) are kept."""
    terms = [m.group(0).lower().strip("-.") for m in _QUERY_WORD.finditer(query)]
    return list(dict.fromkeys(t for t in terms if t and t not in STOPWORDS))


def term_frequencies(text: str, top: int = 60) -> dict[str, float]:
    """Normalised term frequencies of the most frequent content words."""
    counts = Counter(tokenize(text))
    if not counts:
        return {}
    most = counts.most_common(top)
    peak = most[0][1]
    return {term: n / peak for term, n in most}


def chunk_text(text: str, target: int = 1200, overlap: int = 150) -> list[str]:
    """Split on paragraph boundaries into chunks of roughly ``target`` characters."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        while len(para) > target * 2:  # very long paragraph: hard split
            head, para = para[:target], para[target - overlap:]
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(head)
        if buf and len(buf) + len(para) > target:
            chunks.append(buf)
            buf = buf[-overlap:] + "\n\n" + para if overlap else para
        else:
            buf = f"{buf}\n\n{para}" if buf else para
    if buf:
        chunks.append(buf)
    return chunks or ([text.strip()] if text.strip() else [])


def title_from_text(text: str) -> str | None:
    for line in text.splitlines()[:15]:
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None
