"""The EduTrellis Test Series platform as the main site shows it: the navbar
link, the homepage "Explore our Test Series platform" section, and what search
engines are told about it (myapp.seo). One list, so they never disagree.

Every link goes to settings.TEST_SERIES_URL (env TEST_SERIES_URL); until that
is set, links point at the homepage section itself.
"""
from django.conf import settings

SITE = 'https://www.edutrellis.in'
SECTION_ANCHOR = '#test-series'

# icon (Font Awesome), name, one-line description, tags, accent colour, search keywords
SERIES = [
    ('fa-atom', 'JEE Main & Advanced', 'Physics, Chemistry and Maths on the real JEE pattern',
     ['Full mocks', 'Chapter tests', 'PYQs'], '#e8001e', 'JEE Main mock test, JEE Advanced test series'),
    ('fa-stethoscope', 'NEET UG', 'Biology-heavy mocks timed exactly like the real NEET',
     ['Full mocks', 'NCERT-based', 'PYQs'], '#16a34a', 'NEET mock test, NEET test series'),
    ('fa-building-columns', 'UPSC Prelims', 'General Studies and CSAT papers with detailed answers',
     ['GS + CSAT', 'Current affairs', 'PYQs'], '#7c3aed', 'UPSC prelims test series, CSAT mock test'),
    ('fa-file-signature', 'SSC CGL & CHSL', 'Tier-wise tests for reasoning, quant, English and GK',
     ['Tier 1 & 2', 'Sectional', 'Speed tests'], '#2563eb', 'SSC CGL mock test, SSC CHSL test series'),
    ('fa-landmark', 'Banking: IBPS & SBI', 'PO and Clerk prelims and mains with sectional timers',
     ['PO & Clerk', 'Prelims + Mains', 'Puzzles'], '#0891b2', 'IBPS PO mock test, SBI clerk test series'),
    ('fa-train', 'Railways: RRB NTPC', 'CBT 1 and CBT 2 practice on the latest pattern',
     ['CBT 1 & 2', 'Group D', 'GK boosters'], '#ea580c', 'RRB NTPC mock test, railway test series'),
    ('fa-graduation-cap', 'CUET UG', 'Domain subjects, languages and the general test',
     ['Domain tests', 'General test', 'Languages'], '#db2777', 'CUET mock test, CUET UG test series'),
    ('fa-book-open', 'Class 10 & 12 Boards', 'CBSE sample-paper style tests for every main subject',
     ['CBSE', 'Sample papers', 'Chapter-wise'], '#ca8a04', 'CBSE board mock test, class 10 and 12 test series'),
]

NAME = 'EduTrellis Test Series'
DESCRIPTION = ('Online test series and mock tests for JEE, NEET, UPSC, SSC, banking, railways, CUET and '
               'CBSE boards: full-length mocks, sectional tests and previous year papers on the real exam pattern.')


PAGE_URL = SITE + '/test-series/'   # the page on the main site (sitemap, footer, Google sitelinks)

FAQS = [
    ('Which exams does the EduTrellis Test Series cover?',
     'JEE Main & Advanced, NEET UG, UPSC Prelims, SSC CGL & CHSL, banking (IBPS & SBI PO and Clerk), '
     'railways (RRB NTPC), CUET UG and Class 10 & 12 CBSE boards.'),
    ('What kinds of tests are there?',
     'Full-length mock tests on the real exam pattern, sectional and chapter-wise tests, and previous year papers.'),
    ('Where do I take the tests?',
     'On the EduTrellis Test Series platform at exams.edutrellis.in, in any browser on your phone or computer.'),
]


def url():
    """Where every Test Series link goes (relative to the homepage until set)."""
    return (getattr(settings, 'TEST_SERIES_URL', '') or '').strip() or '/' + SECTION_ANCHOR


def absolute_url():
    link = url()
    return link if link.startswith('http') else SITE + link


def cards():
    return [{'icon': icon, 'name': name, 'desc': desc, 'tags': tags, 'color': color}
            for icon, name, desc, tags, color, _ in SERIES]


def keywords():
    return [kw.strip() for *_, kws in SERIES for kw in kws.split(',')]
