"""The 300 sample people on the EduChats Maps tab (exampleN@gmail.com).

    python manage.py educhats_demo_users            # how many there are
    python manage.py educhats_demo_users --delete   # remove them all
    python manage.py educhats_demo_users --create   # add them back (skips emails already in use)
"""
from importlib import import_module

from django.apps import apps
from django.core.management.base import BaseCommand

from ai_app.models import ChatUser


class Command(BaseCommand):
    help = 'Count, delete or re-create the sample users shown on the EduChats Maps tab.'

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='Delete every demo user and their map pin.')
        parser.add_argument('--create', action='store_true', help='Create the 300 demo users again.')

    def handle(self, *args, **opts):
        if opts['delete']:
            n = ChatUser.objects.filter(is_demo=True).count()
            ChatUser.objects.filter(is_demo=True).delete()
            self.stdout.write(self.style.SUCCESS(f'Deleted {n} demo users.'))
        elif opts['create']:
            ChatUser.objects.filter(is_demo=True).delete()
            import_module('ai_app.migrations.0030_demo_map_users').create_demo_users(apps, None)
            self.stdout.write(self.style.SUCCESS(f'Created {ChatUser.objects.filter(is_demo=True).count()} demo users.'))
        else:
            self.stdout.write(f'{ChatUser.objects.filter(is_demo=True).count()} demo users.')
