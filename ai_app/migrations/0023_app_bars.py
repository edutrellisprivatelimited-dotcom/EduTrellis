from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ai_app', '0022_app_lock'),
    ]

    operations = [
        migrations.AddField(
            model_name='educhatsappsettings',
            name='bars_mode',
            field=models.CharField(choices=[('match', 'Match the chat screen'), ('custom', 'Custom colours')], default='match', max_length=8),
        ),
        migrations.AddField(
            model_name='educhatsappsettings',
            name='nav_color',
            field=models.CharField(default='#0f1623', max_length=7),
        ),
    ]
