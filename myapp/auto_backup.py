"""Automatic database backups to Dropbox (Dashboard → Backup & Restore →
Settings: on/off, how often, how many to keep).

One background thread in the web server checks every few minutes whether a
backup is due. Only the live server runs it (settings.AUTO_BACKUP_RUNS), so a
developer's laptop never writes backups into the production Dropbox. Claiming
a run is a conditional UPDATE on DropboxSettings.last_auto_backup_at, so two
processes can never both take the same backup.
"""
import logging
import sys
import threading
import time
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)

FIRST_CHECK_SECONDS = 5 * 60     # let the server finish starting (and organize_media run) first
CHECK_EVERY_SECONDS = 10 * 60
RETRY_AFTER_FAILURE = timedelta(hours=1)

_started = False
_lock = threading.Lock()


def next_due(settings_obj):
    """When the next automatic backup is due (None when switched off)."""
    if not settings_obj.auto_backup_enabled or not settings_obj.is_configured:
        return None
    last = settings_obj.last_auto_backup_at
    if not last:
        return timezone.now()
    gap = timedelta(hours=settings_obj.auto_backup_every_hours or 24)
    if settings_obj.last_auto_backup_error:
        gap = min(gap, RETRY_AFTER_FAILURE)
    return last + gap


def run_if_due():
    """Takes one automatic backup when it's due. Returns the file name, or None."""
    from . import dropbox_backup
    from .models import DropboxSettings
    obj = DropboxSettings.get_solo()
    due = next_due(obj)
    now = timezone.now()
    if due is None or due > now:
        return None
    # Claim this run: only the process whose UPDATE matches goes ahead.
    claimed = DropboxSettings.objects.filter(pk=obj.pk, last_auto_backup_at=obj.last_auto_backup_at) \
        .update(last_auto_backup_at=now)
    if not claimed:
        return None
    try:
        name = dropbox_backup.create_backup(obj, kind=dropbox_backup.KIND_AUTO)
    except dropbox_backup.BackupError as exc:
        if 'already running' in str(exc):
            # A manual backup or restore is busy; try again on the next check.
            DropboxSettings.objects.filter(pk=obj.pk).update(last_auto_backup_at=obj.last_auto_backup_at)
            return None
        DropboxSettings.objects.filter(pk=obj.pk).update(last_auto_backup_error=str(exc)[:300])
        logger.warning('Automatic backup failed: %s', exc)
        return None
    DropboxSettings.objects.filter(pk=obj.pk).update(last_auto_backup_error='')
    try:
        dropbox_backup.prune_auto_backups(obj, obj.auto_backup_keep or 14)
    except dropbox_backup.BackupError as exc:
        logger.warning('Could not remove old automatic backups: %s', exc)
    logger.info('Automatic backup saved as %s', name)
    return name


def _loop():
    time.sleep(FIRST_CHECK_SECONDS)
    while True:
        close_old_connections()
        try:
            run_if_due()
        except Exception:
            logger.exception('Automatic backup check failed')
        finally:
            close_old_connections()
        time.sleep(CHECK_EVERY_SECONDS)


def start():
    """Called once from MyappConfig.ready(); only the live web server runs it."""
    global _started
    if not getattr(settings, 'AUTO_BACKUP_RUNS', False):
        return
    if 'gunicorn' not in sys.argv[0] and not any('gunicorn' in a for a in sys.argv[:2]):
        return   # migrate, collectstatic, shell … never back up
    with _lock:
        if _started:
            return
        _started = True
    threading.Thread(target=_loop, name='auto-backup', daemon=True).start()
