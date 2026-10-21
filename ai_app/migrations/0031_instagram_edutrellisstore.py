"""EduTrellis's Instagram moved from @edutrellis to @edutrellisstore. Updates
the saved EduChats Support profile (and any EduTrellis account on EduChats)
that still links the old profile; other people's own links are untouched."""
from django.db import migrations

OLD = ('https://www.instagram.com/edutrellis', 'https://www.instagram.com/edutrellis/',
       'https://instagram.com/edutrellis', 'https://instagram.com/edutrellis/')
NEW = 'https://www.instagram.com/edutrellisstore'


def forwards(apps, schema_editor):
    for model in ('SupportProfile', 'ChatUser'):
        apps.get_model('ai_app', model).objects.filter(instagram__in=OLD).update(instagram=NEW)


class Migration(migrations.Migration):
    dependencies = [('ai_app', '0030_demo_map_users')]
    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
