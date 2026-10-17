"""Tokenisation and term matching for English and Chinese engineering text.

Plain substring matching misfires on Latin text ("edge" inside "knowledge",
"ncr" inside "encroachment"). Latin terms therefore match on word
boundaries; Chinese has no spaces, so CJK terms match as substrings and are
indexed as overlapping character bigrams for retrieval.
"""
from __future__ import annotations

import re

_LATIN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")
_CJK = re.compile(r"[一-鿿]+")
_HAS_CJK = re.compile(r"[一-鿿]")


# Function words carry no engineering meaning and would make unrelated
# messages "match" a source.
STOPWORDS = frozenset("""a an and are as at be been but by can could do does for from had has have he her his i if in
into is it its just me my no not of on or our out over please she so some such than that the their them then there
these they this those to too up us was we were what when where which while who will with would you your yes hello hi
thanks thank just about after again all also any because before being both did each few more most other own same
should only very via per new""".split())
_CJK_STOP = frozenset(["一个", "我们", "你们", "他们", "这个", "那个", "就是", "还有", "以及", "如果", "因为", "所以", "可以", "需要",
                       "进行", "已经", "没有", "什么", "怎么", "是否", "下午", "上午", "今天", "明天", "周五"])


def tokens(text: str) -> list[str]:
    """Latin words (minus stopwords) plus CJK character bigrams, lower-cased."""
    lower = text.lower()
    out = [w for w in _LATIN.findall(lower) if w not in STOPWORDS and (len(w) > 1 or w.isdigit())]
    for run in _CJK.findall(lower):
        if len(run) == 1:
            continue
        out.extend(b for b in (run[i:i + 2] for i in range(len(run) - 1)) if b not in _CJK_STOP)
    return out


def has_term(text: str, term: str) -> bool:
    """True if ``term`` occurs in ``text`` as a word (Latin) or substring (CJK)."""
    term = term.lower().strip()
    if not term:
        return False
    if _HAS_CJK.search(term):
        return term in text.lower()
    return re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text.lower()) is not None


def matched(text: str, terms: list[str] | tuple[str, ...]) -> list[str]:
    return [t for t in terms if has_term(text, t)]
