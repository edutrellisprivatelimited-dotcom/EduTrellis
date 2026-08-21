"""Fast, dependency-free intent classification for automatic model routing.

This runs on every chat request, so importing and training a machine-learning
pipeline here adds a large cold-start delay for very little benefit. A small
keyword scorer is deterministic, starts instantly, and preserves the existing
route categories.
"""
import re


_TOKEN_RE = re.compile(r"[a-z0-9+#.-]+")
_KEYWORDS = {
    'code': {
        'api', 'bug', 'code', 'coding', 'css', 'database', 'debug', 'django',
        'error', 'exception', 'html', 'java', 'javascript', 'node', 'php',
        'program', 'programming', 'python', 'react', 'sql', 'traceback',
        'typescript',
    },
    'research': {
        'compare', 'current', 'evidence', 'fact', 'facts', 'latest', 'news',
        'research', 'source', 'sources', 'study', 'today', 'verify',
    },
    'shopping': {
        'buy', 'order', 'price', 'product', 'recommend', 'shop', 'shopping',
        'store',
    },
    'document': {
        'document', 'file', 'pdf', 'presentation', 'spreadsheet', 'summarize',
        'summary',
    },
    'creative': {
        'brainstorm', 'caption', 'creative', 'email', 'poem', 'rewrite',
        'story',
    },
}
_CATEGORY_PRIORITY = ('code', 'research', 'shopping', 'document', 'creative')


def classify(text):
    tokens = set(_TOKEN_RE.findall((text or '').lower()))
    if not tokens:
        return 'general'

    scores = {
        category: len(tokens.intersection(keywords))
        for category, keywords in _KEYWORDS.items()
    }
    best_score = max(scores.values(), default=0)
    if not best_score:
        return 'general'
    return next(category for category in _CATEGORY_PRIORITY if scores[category] == best_score)


def choose_model(text, default_model):
    category = classify(text)
    return {'code': 'code', 'research': 'light'}.get(category, default_model), category
