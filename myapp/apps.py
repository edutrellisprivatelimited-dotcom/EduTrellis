from django.apps import AppConfig


class MyappConfig(AppConfig):
    name = 'myapp'

    def ready(self):
        # Automatic Dropbox backups (live server only, see auto_backup.start).
        from . import auto_backup
        auto_backup.start()
