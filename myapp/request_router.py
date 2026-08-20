"""Lightweight local intent classification for automatic model routing."""
_classifier = None

_EXAMPLES = [
    ('debug this python error write code fix api css javascript', 'code'),
    ('research current news latest facts compare sources explain topic', 'research'),
    ('find product buy price recommend shopping order store', 'shopping'),
    ('summarize spreadsheet pdf presentation document file', 'document'),
    ('write story email caption brainstorm creative rewrite', 'creative'),
    ('hello advice explain question conversation', 'general'),
]


def classify(text):
    global _classifier
    try:
        if _classifier is None:
            from sklearn.feature_extraction.text import TfidfVectorizer
            from sklearn.pipeline import make_pipeline
            from sklearn.svm import LinearSVC
            samples, labels = zip(*_EXAMPLES)
            _classifier = make_pipeline(TfidfVectorizer(ngram_range=(1, 2)), LinearSVC()).fit(samples, labels)
        return str(_classifier.predict([text or ''])[0])
    except Exception:
        lowered = (text or '').lower()
        return 'code' if any(k in lowered for k in ('code', 'error', 'python', 'javascript')) else 'general'


def choose_model(text, default_model):
    category = classify(text)
    return {'code': 'code', 'research': 'light'}.get(category, default_model), category
