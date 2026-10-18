from django.apps import AppConfig


class AiAppConfig(AppConfig):
    name = 'ai_app'
    verbose_name = 'EduTrellis AI'

    def ready(self):
        from . import signals  # noqa: F401
