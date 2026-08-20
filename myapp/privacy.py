"""Remove common personal identifiers before text is sent to an LLM."""
import re


_FALLBACK_PATTERNS = (
    (re.compile(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b'), '<EMAIL>'),
    (re.compile(r'(?<!\d)(?:\+?91[- ]?)?[6-9]\d{9}(?!\d)'), '<PHONE>'),
    (re.compile(r'\b(?:\d[ -]*?){13,19}\b'), '<PAYMENT_NUMBER>'),
)
_analyzer = _anonymizer = None
_presidio_unavailable = False


def redact(text):
    if not text:
        return text
    global _analyzer, _anonymizer, _presidio_unavailable
    try:
        if _presidio_unavailable:
            raise RuntimeError('Presidio unavailable')
        if _analyzer is None:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine
            _analyzer, _anonymizer = AnalyzerEngine(), AnonymizerEngine()
        findings = _analyzer.analyze(text=text, language='en')
        return _anonymizer.anonymize(text=text, analyzer_results=findings).text
    except Exception:
        _presidio_unavailable = True
        for pattern, replacement in _FALLBACK_PATTERNS:
            text = pattern.sub(replacement, text)
        return text
