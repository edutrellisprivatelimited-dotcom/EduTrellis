"""Search-engine and AI-answer data for the public site: one schema.org graph
(the company, its founder/CEO, the website and its main sections) that every
public page embeds, plus the plain-text /llms.txt summary AI assistants read.

Contact details come from business_info, the founder/CEO from the dashboard's
Customize > Founder page (FounderSection) — so changing either there updates
Google's and the AI engines' view of the company too. A blank founder name
leaves the person out entirely rather than guessing one."""

import json

from django.http import HttpResponse
from django.template.loader import render_to_string

from myapp import business_info as biz

SITE = 'https://www.edutrellis.in'
ORG_ID = SITE + '/#organization'
FOUNDER_ID = SITE + '/#founder'

# The site's main sections, most important first. This is the order the
# footer's "Explore EduTrellis" column lists them and the order given to
# search engines — Google picks its sitelinks itself, but it leans on the
# pages a site links to most prominently and describes most clearly.
SECTIONS = [
    ('Website Development & SEO Services', SITE + '/',
     'Website design, development and management, SEO, Meta Ads and Google Business Profile services for businesses across India.'),
    ('EduTrellis Store', SITE + '/store/',
     'Official EduTrellis online store: EduTrellis AI plans, speakers, gadgets and toys with delivery across India.'),
    ('EduTrellis AI', SITE + '/ai/',
     'EduTrellis AI chat assistant: chat, reasoning, coding, image understanding and image generation in the browser.'),
    ('EduChats', SITE + '/educhats/',
     'EduChats: chat directly with EduTrellis support and with other people.'),
    ('Contact EduTrellis', SITE + '/#contact',
     f'Call or WhatsApp {biz.PHONE_DISPLAY}, email {biz.EMAIL_SUPPORT}, or write to the CEO at {biz.EMAIL_CEO}.'),
]


def founder():
    """The founder/CEO as the dashboard has them, or None when unnamed."""
    from myapp.models import FounderSection
    f = FounderSection.get_solo()
    if not (f.is_active and (f.name or '').strip()):
        return None
    return f


def _postal_address():
    return {
        '@type': 'PostalAddress',
        'streetAddress': biz.ADDRESS_STREET,
        'addressLocality': biz.ADDRESS_CITY,
        'addressRegion': biz.ADDRESS_STATE,
        'postalCode': biz.ADDRESS_ZIP,
        'addressCountry': biz.ADDRESS_COUNTRY,
    }


def graph(logo_url):
    same_as = [biz.INSTAGRAM_URL, biz.LINKEDIN_COMPANY_URL, biz.FACEBOOK_URL]
    org = {
        '@type': ['Organization', 'LocalBusiness'],
        '@id': ORG_ID,
        'name': 'EduTrellis',
        'legalName': biz.LEGAL_NAME,
        'url': SITE + '/',
        'logo': logo_url,
        'image': logo_url,
        'description': ('EduTrellis is a digital growth company in Lucknow, India: website development '
                        'and management, SEO and digital marketing, the EduTrellis online store, '
                        'EduTrellis AI and EduChats.'),
        'email': biz.EMAIL_SUPPORT,
        'telephone': biz.PHONE_E164,
        'address': _postal_address(),
        'areaServed': 'India',
        'openingHours': ['Mo-Sa 09:00-20:00', 'Su 10:00-18:00'],
        'sameAs': same_as,
        'contactPoint': [
            {'@type': 'ContactPoint', 'contactType': 'customer support', 'telephone': biz.PHONE_E164,
             'email': biz.EMAIL_SUPPORT, 'areaServed': 'IN', 'availableLanguage': ['English', 'Hindi']},
            {'@type': 'ContactPoint', 'contactType': 'business enquiries', 'telephone': biz.PHONE_E164,
             'email': biz.EMAIL_CEO, 'areaServed': 'IN', 'availableLanguage': ['English', 'Hindi']},
        ],
    }
    nodes = [org]
    f = founder()
    if f:
        person = {
            '@type': 'Person',
            '@id': FOUNDER_ID,
            'name': f.name.strip(),
            'jobTitle': f.title or 'Founder & CEO',
            'email': f.email or biz.EMAIL_CEO,
            'telephone': biz.PHONE_E164,
            'worksFor': {'@id': ORG_ID},
            'url': SITE + '/#clients',
        }
        if f.linkedin:
            person['sameAs'] = [f.linkedin]
        if f.photo:
            person['image'] = SITE + f.photo.url
        nodes.append(person)
        org['founder'] = {'@id': FOUNDER_ID}
        org['employee'] = [{'@id': FOUNDER_ID}]
    nodes.append({
        '@type': 'WebSite',
        '@id': SITE + '/#website',
        'name': 'EduTrellis',
        'url': SITE + '/',
        'inLanguage': 'en-IN',
        'publisher': {'@id': ORG_ID},
    })
    nodes.append({
        '@type': 'ItemList',
        '@id': SITE + '/#sections',
        'name': 'EduTrellis main sections',
        'itemListElement': [
            {'@type': 'SiteNavigationElement', 'position': i, 'name': name, 'url': url, 'description': desc}
            for i, (name, url, desc) in enumerate(SECTIONS, 1)
        ],
    })
    return {'@context': 'https://schema.org', '@graph': nodes}


def to_script_json(data):
    """JSON that is safe inside a <script> element even with admin-typed text."""
    return (json.dumps(data, ensure_ascii=False)
            .replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026'))


def llms_txt(request):
    """/llms.txt — a plain summary of who EduTrellis is for AI assistants and
    AI search (ChatGPT, Gemini, Perplexity, Claude …), see llmstxt.org."""
    from myapp.models import Product
    products = Product.objects.filter(is_active=True).order_by('order', 'id')
    body = render_to_string('llms.txt', {
        'BIZ': biz.as_dict(), 'founder': founder(), 'sections': SECTIONS, 'site': SITE,
        'products': products,
    })
    response = HttpResponse(body, content_type='text/plain; charset=utf-8')
    response['Cache-Control'] = 'public, max-age=3600'
    return response
