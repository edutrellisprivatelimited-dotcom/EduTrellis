from django.db import migrations

OLD_URL = 'https://www.vidhyora.online/'
NEW_URL = 'https://www.edutrellis.in/ai/'


def point_at_internal_ai(apps, schema_editor):
    NavAISettings = apps.get_model('myapp', 'NavAISettings')
    # Only touch a row still pointing at the retired external site — never
    # overwrite a URL staff have since customized to something else.
    NavAISettings.objects.filter(url=OLD_URL).update(url=NEW_URL)


def revert(apps, schema_editor):
    NavAISettings = apps.get_model('myapp', 'NavAISettings')
    NavAISettings.objects.filter(url=NEW_URL).update(url=OLD_URL)


class Migration(migrations.Migration):

    dependencies = [
        ('myapp', '0062_alter_navaisettings_url'),
    ]

    operations = [
        migrations.RunPython(point_at_internal_ai, revert),
    ]
