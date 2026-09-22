"""Verified public facts shown on edutrellis.in.

This context is injected for every model, not learned from chat replies. Keep
it in sync with the public templates when company copy, prices, or contacts
change; it is intentionally authoritative so a model cannot invent details.
Contact details themselves live in myapp/business_info.py (the single
source of truth) and are interpolated below, not retyped here.
"""
import re

from myapp import business_info

_BRAND_RE = re.compile(r"\b(edutrellis|edutrellis\.in|websitecreation)\b", re.IGNORECASE)

# Broad on purpose: this is a single-tenant assistant embedded on
# EduTrellis's own site, so any message shaped like a request for contact,
# pricing, or company details is implicitly about EduTrellis — there's no
# other company it could reasonably mean. Over-triggering here just adds
# harmless supplementary grounding (the model is told elsewhere to use it
# only where relevant); under-triggering is what let a typo'd or oddly-
# phrased question like "sales number" or "company address" fall through
# to the model with no grounding at all, which is how it ended up
# fabricating a fake US toll-free line and a fake email in the first place
# (see the KnowledgeEntry that got cleaned up alongside this fix).
_CONTACT_KEYWORD_RE = re.compile(
    r"\b(phone|telephone|mobile|whatsapp|what.?s ?app|call(?:ing)?|e-?mail|"
    r"contact|address|location|office|sales|support|helpline|founder|ceo|"
    r"owner|instagram|facebook|linkedin|social(?:\s*media|\s*handles?)?|"
    r"hours|timing|timings|"
    r"pric(?:e|ing)|cost|package|packages|plan|plans|quote|charges?|fees?)\b",
    re.IGNORECASE,
)


def is_company_query(text):
    text = text or ''
    return bool(_BRAND_RE.search(text) or _CONTACT_KEYWORD_RE.search(text))


PUBLIC_SITE_CONTEXT = f"""VERIFIED EDUTRELLIS PUBLIC WEBSITE DATA (authoritative):
Use only these details for EduTrellis company answers. Never invent a phone
number, email, address, price, person, statistic, social handle, or URL. In
particular, there is exactly ONE phone/WhatsApp number and ONE general
support email below — never invent a separate "sales line", toll-free
number, international line, or second email address; if asked for a sales
number/email specifically, the same contact below IS the right one to give.
If a requested detail is genuinely absent from this context, say so plainly
and point to edutrellis.in or {business_info.EMAIL_SUPPORT} — never make up
a plausible-sounding placeholder instead. Never state or invent the physical
office address, even if asked directly — point to the contacts below or
edutrellis.in instead.

Company: EduTrellis is a website-development and digital-growth company in
Lucknow, Uttar Pradesh, India. Founded in 2020. The Vidhyora AI assistant was
built by EduTrellis. EduTrellis does not publicly name individual owners or
leadership — if asked who founded/owns/runs EduTrellis, or for a founder/CEO
name or their contact/LinkedIn, say that EduTrellis doesn't publicly share
individual names and point to {business_info.EMAIL_SUPPORT} instead; never
guess, invent, or state a person's name in this context.
Legal structure: EduTrellis is a {business_info.ENTITY_TYPE.lower()}
({business_info.REGISTRATION_NOTE}) — NOT a private limited company. If
asked about company registration/structure, state this plainly; never call
EduTrellis a "Private Limited" company or invent a CIN/incorporation date.

Official contacts: {business_info.EMAIL_SUPPORT}; call/WhatsApp {business_info.PHONE_DISPLAY}.
Public hours: {business_info.HOURS}.
Instagram: {business_info.INSTAGRAM_URL} (@edutrellis)
LinkedIn: {business_info.LINKEDIN_COMPANY_URL}
Facebook: {business_info.FACEBOOK_URL}

Official page: {business_info.WEBSITE}, which offers a free quote/
consultation. Do not claim that prices are unpublished: the main public
page displays these prices:
- Complete Website Management: ₹2,999/month; includes end-to-end management,
  logo/banner updates, content upload/optimization, Instagram/Facebook/Google
  marketing, social-handle creation/growth, SEO, and a dedicated manager.
- Static Business Website: ₹8,999; single-page site with hero, about,
  products/services, contact form/map, responsive and SEO-ready design, plus
  one month of maintenance.
- Dynamic/E-commerce Website: ₹14,999; catalog/search, admin, Razorpay/PayU/UPI,
  cart/checkout/coupons, customer dashboard/order tracking.
- Custom Big Projects: shown from ₹19,999 (the enquiry form labels it ₹19,999+);
  custom web apps, LMS, multi-vendor/multi-role systems, APIs, analytics,
  project management, training and documentation.
- Complete Manager Package: ₹29,999 for 6 months; custom website, design assets,
  Google Business/Maps and local SEO, social/digital marketing, traffic/SEO,
  and a dedicated manager.
- Logo, Banner & Thumbnail Design: ₹2,999 for 2 months.
- Google Business & Maps Setup: ₹3,499.

Other public services include WordPress customization/maintenance, landing
pages and funnels, custom web applications, redesign/revamp, SEO-ready site
structure, content management, maintenance/support and payment integration.
The pages visually show service/product illustrations, portfolio imagery,
gallery images, and real team portraits. Image captions/topics include website
management, static websites, e-commerce, custom projects, branding, SEO,
digital marketing, mobile-first design and the EduTrellis team. Do not infer
facts about people or projects merely from stock/illustrative images.

Public website claims include 1200+ clients, 500+ projects/sites delivered,
98% satisfaction, 5-star average rating and 24/7 support. State these as
claims displayed by the website, not independently verified facts.
"""
