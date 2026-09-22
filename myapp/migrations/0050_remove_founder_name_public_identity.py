import re

from django.db import migrations

# The business no longer publishes an individual name as founder/CEO/owner
# anywhere (site copy, legal pages, AI knowledge) — matches the
# corresponding ai_chat.py/company_knowledge.py prompt changes and the
# template edits removing the "Meet Our Founder" section. Same pattern as
# 0036_fix_rudra_role_knowledge.py / 0044_remove_personal_name_and_address_knowledge.py.
TOPIC_UPDATES = {
    'EduTrellis team': (
        "EduTrellis does not publicly share the names of individual owners, "
        "leadership or staff. For team or staff inquiries, contact "
        "support@edutrellis.in. The EduTrellis AI chat assistant (a separate "
        "feature from the company itself) was built by EduTrellis."
    ),
    'EduTrellis AI creator': (
        "The EduTrellis AI chat feature (this assistant) was built by "
        "EduTrellis, the company. EduTrellis does not publicly name an "
        "individual as its creator, founder or owner."
    ),
    'EduTrellis founder and CEO': (
        "EduTrellis does not publicly share the name of its founder, CEO or "
        "owner. For any business inquiry, contact support@edutrellis.in."
    ),
}

# Any auto-learned ("chat"/"web_search" sourced) entry that cached a
# now-retired personal name into a reply — same reasoning as
# 0042_purge_fake_contact_knowledge.py / 0044's purge of stale info.
_STALE_NAME_RE = re.compile(r"Vijay", re.IGNORECASE)

UPDATED_POLICIES = {
    'terms': (
        "jurisdiction of the courts in Lucknow, Uttar Pradesh. Grievance Officer: EduTrellis Support "
        "Team, ceo@edutrellis.in, P-109, Prembagh, Shahpur, Chinhat, Lucknow, Uttar Pradesh 226028."
    ),
    'privacy': (
        "Grievance Officer: in accordance with the Information Technology Act, 2000 and rules made "
        "under it, complaints or concerns about this policy can be sent to our Grievance Officer, the "
        "EduTrellis Support Team, at ceo@edutrellis.in; we aim to acknowledge complaints within 24 "
        "hours and resolve them within 15 days.\n\n"
        "We may update this policy from time to time; the latest version will always be available on "
        "this page. If you have questions about this policy, contact us at support@edutrellis.in."
    ),
}


def scrub_founder_name(apps, schema_editor):
    KnowledgeEntry = apps.get_model('myapp', 'KnowledgeEntry')
    shared = {'user__isnull': True, 'session_key': ''}
    for topic, content in TOPIC_UPDATES.items():
        KnowledgeEntry.objects.filter(topic=topic, source='manual', **shared).update(content=content)
    stale_ids = [
        entry.pk for entry in KnowledgeEntry.objects.exclude(source='manual')
        if _STALE_NAME_RE.search(entry.topic) or _STALE_NAME_RE.search(entry.content)
    ]
    if stale_ids:
        KnowledgeEntry.objects.filter(pk__in=stale_ids).delete()

    PolicyPage = apps.get_model('myapp', 'PolicyPage')
    terms = PolicyPage.objects.filter(key='terms').first()
    if terms and 'Vijay Tiwari' in terms.content:
        terms.content = terms.content.replace(
            "jurisdiction of the courts in Lucknow, Uttar Pradesh. Grievance Officer: Vijay Tiwari "
            "(Founder & CEO), ceo@edutrellis.in, P-109, Prembagh, Shahpur, Chinhat, Lucknow, Uttar "
            "Pradesh 226028.",
            UPDATED_POLICIES['terms'],
        )
        terms.save(update_fields=['content'])

    privacy = PolicyPage.objects.filter(key='privacy').first()
    if privacy and 'Vijay Tiwari' in privacy.content:
        privacy.content = privacy.content.replace(
            "Grievance Officer: in accordance with the Information Technology Act, 2000 and rules made "
            "under it, complaints or concerns about this policy can be sent to our Grievance Officer, "
            "Vijay Tiwari (Founder & CEO), at ceo@edutrellis.in; we aim to acknowledge complaints within "
            "24 hours and resolve them within 15 days.\n\n"
            "We may update this policy from time to time; the latest version will always be available on "
            "this page. If you have questions about this policy, contact us at support@edutrellis.in.",
            UPDATED_POLICIES['privacy'],
        )
        privacy.save(update_fields=['content'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0049_alter_aboutuscontent_paragraph1'),
    ]

    operations = [
        migrations.RunPython(scrub_founder_name, noop_reverse),
    ]
