"""EduChats → Maps is gone: delete the sample map users (exampleN@gmail.com),
then the MapSpot table and the ChatUser.is_demo flag."""
from django.db import migrations


def delete_demo_users(apps, schema_editor):
    apps.get_model('ai_app', 'ChatUser').objects.filter(is_demo=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('ai_app', '0032_remove_aisitesettings_site_disabled_and_more'),
    ]

    operations = [
        migrations.RunPython(delete_demo_users, migrations.RunPython.noop),
        migrations.DeleteModel(name='MapSpot'),
        migrations.RemoveField(model_name='chatuser', name='is_demo'),
    ]
