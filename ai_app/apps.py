from django.apps import AppConfig


class AiAppConfig(AppConfig):
    name = 'ai_app'
    verbose_name = 'EduTrellis AI'

    def ready(self):
        from . import educhats_push, signals  # noqa: F401  (EduChats notifications hook into post_save)
