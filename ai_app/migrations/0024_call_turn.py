from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_app', '0023_app_bars'),
    ]

    operations = [
        migrations.AddField(model_name='educhatsappsettings', name='turn_url', field=models.CharField(blank=True, max_length=300)),
        migrations.AddField(model_name='educhatsappsettings', name='turn_username', field=models.CharField(blank=True, max_length=120)),
        migrations.AddField(model_name='educhatsappsettings', name='turn_credential', field=models.CharField(blank=True, max_length=200)),
    ]
