"""Retrieval logic for the EduTrellis Light model: check the saved
KnowledgeEntry table first (fast, free, no external call), and only fall
back to a live web search (myapp.web_search, via Tavily) when nothing
relevant is found — saving the top result back to the knowledge base so the
same question is a knowledge-base hit next time instead of another search.
"""
import re

from django.db.models import Q

from myapp import web_search
from myapp.models import KnowledgeEntry

MIN_KEYWORD_LEN = 3
KB_MAX_ENTRIES = 3
KB_CONTEXT_MAX_CHARS = 4000
WEB_CONTEXT_MAX_CHARS = 4000
_STOPWORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'what', 'how', 'why', 'who',
    'when', 'where', 'does', 'do', 'did', 'can', 'could', 'should', 'would',
    'for', 'and', 'or', 'of', 'to', 'in', 'on', 'at', 'it', 'this', 'that',
    'you', 'your', 'me', 'my', 'please', 'tell', 'about',
}


def _keywords(text):
    words = re.findall(r"[a-zA-Z0-9']+", (text or '').lower())
    return [w for w in words if len(w) >= MIN_KEYWORD_LEN and w not in _STOPWORDS]


def search_knowledge_base(query):
    """Simple substring/keyword match, ranked by how many query keywords
    appear in topic+content — not embeddings, which would be overkill for a
    small, mostly hand-curated table and would work against being 'fast'.
    Requires at least 2 shared keywords AND at least half the query's
    keywords to match — a single incidental shared word (e.g. a year like
    '2026' appearing in both an unrelated saved entry and a brand-new
    question) isn't enough, or a completely unrelated topic can hijack an
    otherwise-uncovered question instead of triggering a fresh search."""
    keywords = _keywords(query)
    if not keywords:
        return []
    q = Q()
    for kw in keywords:
        q |= Q(topic__icontains=kw) | Q(content__icontains=kw)
    candidates = list(KnowledgeEntry.objects.filter(q)[:50])

    def score(entry):
        haystack = (entry.topic + ' ' + entry.content).lower()
        return sum(1 for kw in keywords if kw in haystack)

    min_score = max(2, (len(keywords) + 1) // 2)
    scored = [(c, score(c)) for c in candidates]
    scored = [(c, s) for c, s in scored if s >= min_score]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [c for c, _ in scored][:KB_MAX_ENTRIES]


def context_from_entries(entries):
    blocks, total = [], 0
    for e in entries:
        block = f"### {e.topic}\n{e.content}"
        if total + len(block) > KB_CONTEXT_MAX_CHARS:
            break
        blocks.append(block)
        total += len(block)
    return '\n\n'.join(blocks)


def web_search_and_save(query):
    """Runs a live Tavily search and saves the top result to the knowledge
    base for next time. Returns (context_text, 'web_search'), or
    (None, None) if search is unavailable, fails, or returns nothing."""
    try:
        results = web_search.search(query, max_results=5)
    except web_search.SearchError:
        return None, None
    if not results:
        return None, None

    blocks, total = [], 0
    for r in results:
        block = f"### {r['title']}\nSource: {r['url']}\n{r['content']}"
        if total + len(block) > WEB_CONTEXT_MAX_CHARS:
            break
        blocks.append(block)
        total += len(block)

    top = results[0]
    KnowledgeEntry.objects.create(
        topic=query[:200],
        content=top['content'][:4000],
        source=KnowledgeEntry.SOURCE_WEB,
        source_url=top['url'][:200],
    )
    return '\n\n'.join(blocks), 'web_search'
