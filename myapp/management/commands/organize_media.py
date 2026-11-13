"""Moves files saved under the old top-level Dropbox folders into the organized
layout (myapp/media_folders.py) and points the database at the new names.

    python manage.py organize_media            # do it
    python manage.py organize_media --dry-run  # only list what it would do (reads Dropbox, changes nothing)

Safe to run again and again (the Procfile runs it on every start, after
move_media_to_dropbox): anything already in place is skipped. For each old
folder it:

1. moves the folder in Dropbox (one call), or file by file when the new
   folder already exists;
2. renames StoredFile rows, every FileField in every model, and the text
   fields that hold a /media/ link — but only for files Dropbox really holds
   at the new name, so nothing ever points at a missing file;
3. moves call recordings still on the server's disk to the new folder, and
   uploads finished ones to Dropbox (ai_calls.archive_recording);
4. moves the per-account AI image archive from '/edutrellis-ai' to
   '/EduTrellis Site/ai/archive'.

Until it has run, /media/<old name> still works, and afterwards it redirects
to the new name (myapp.views.media_redirect).
"""
import shutil
from datetime import timedelta
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import models
from django.db.models import Q
from django.utils import timezone

from myapp import dropbox_storage, media_folders


def _is(exc, kind):
    return kind in str(getattr(exc, 'error', exc)).lower()


class Command(BaseCommand):
    help = 'Move old Dropbox media folders into the organized layout and update the database.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Only list what would happen.')

    def handle(self, *args, dry_run=False, **options):
        self.dry_run = dry_run
        self.verbosity = options.get('verbosity', 1)
        self.changed = self.failed = 0
        if not getattr(settings, 'DROPBOX_STORAGE_ENABLED', True):
            self.stdout.write('Dropbox storage is switched off here; nothing to organize.')
            return
        try:
            self.dbx = dropbox_storage.client()
        except dropbox_storage.DropboxFileError as exc:
            self.stderr.write(f'Dropbox is not available: {exc}')
            return
        self.root = dropbox_storage.root()
        for old, new in media_folders.LEGACY_FOLDERS:
            self.move_folder(f'{self.root}/{old.rstrip("/")}', f'{self.root}/{new.rstrip("/")}')
        self.move_folder(_archive_legacy_root(), f'{self.root}/{media_folders.AI_ARCHIVE}')
        self.move_disk_recordings()
        self.in_dropbox = self.list_dropbox()
        self.update_stored_files()
        self.update_file_fields()
        self.update_text_links()
        self.archive_recordings()
        verb = 'Would change' if dry_run else 'Changed'
        self.stdout.write(f'{verb} {self.changed} item(s); {self.failed} failed.')

    # ── Dropbox ────────────────────────────────────────────────────────────

    def move_folder(self, src, dst):
        import dropbox
        try:
            self.dbx.files_get_metadata(src)
        except dropbox.exceptions.ApiError as exc:
            if _is(exc, 'not_found'):
                return
            raise
        self.say(f'move folder {src} -> {dst}')
        if self.dry_run:
            self.changed += 1
            return
        try:
            self.dbx.files_move_v2(src, dst, autorename=False)
            self.changed += 1
            return
        except dropbox.exceptions.ApiError as exc:
            if not _is(exc, 'conflict'):
                self.failed += 1
                self.stderr.write(f'  could not move {src}: {exc}')
                return
        # The new folder already exists (uploads went there): merge file by file.
        for entry in self.walk(src):
            rel = entry.path_display[len(src) + 1:]
            try:
                self.dbx.files_move_v2(entry.path_display, f'{dst}/{rel}', autorename=False)
                self.changed += 1
            except dropbox.exceptions.ApiError as exc:
                if _is(exc, 'conflict'):
                    self.stderr.write(f'  {dst}/{rel} already exists; left {entry.path_display} where it is')
                else:
                    self.failed += 1
                    self.stderr.write(f'  could not move {entry.path_display}: {exc}')
        if not any(True for _ in self.walk(src)):
            try:
                self.dbx.files_delete_v2(src)
            except Exception:
                pass

    def walk(self, folder):
        """Every file under a Dropbox folder."""
        import dropbox
        result = self.dbx.files_list_folder(folder, recursive=True)
        while True:
            for entry in result.entries:
                if isinstance(entry, dropbox.files.FileMetadata):
                    yield entry
            if not result.has_more:
                break
            result = self.dbx.files_list_folder_continue(result.cursor)

    def list_dropbox(self):
        """Lower-cased names of every file now in the site's media folder.
        (On a dry run, names as they will be once the folders have moved.)"""
        names = set()
        prefix = len(self.root) + 1
        try:
            for entry in self.walk(self.root):
                name = entry.path_lower[prefix:]
                names.add(name)
                if self.dry_run:
                    names.add((media_folders.new_name(name) or name).lower())
        except Exception as exc:
            self.stderr.write(f'Could not list Dropbox: {exc}')
        return names

    def exists(self, name):
        if name.lower() in self.in_dropbox:
            return True
        return name.startswith(media_folders.AI_CALLS) and _private_path(name).is_file()

    # ── Database ───────────────────────────────────────────────────────────

    def legacy_q(self, field):
        q = Q()
        for old, _ in media_folders.LEGACY_FOLDERS:
            q |= Q(**{f'{field}__startswith': old})
        return q

    def update_stored_files(self):
        from myapp.models import StoredFile
        for pk, name in StoredFile.objects.filter(self.legacy_q('name')).values_list('pk', 'name'):
            new = media_folders.new_name(name)
            if not self.exists(new):
                continue
            self.say(f'file record {name} -> {new}')
            self.changed += 1
            if self.dry_run:
                continue
            if StoredFile.objects.filter(name=new).exists():
                StoredFile.objects.filter(pk=pk).delete()
            else:
                # The permanent link is made again for the new path.
                StoredFile.objects.filter(pk=pk).update(name=new, url='')

    def update_file_fields(self):
        for model in apps.get_models():
            for field in model._meta.concrete_fields:
                if not isinstance(field, models.FileField):
                    continue
                rows = model._base_manager.filter(self.legacy_q(field.attname)).values_list('pk', field.attname)
                for pk, name in rows.iterator():
                    new = media_folders.new_name(name)
                    if not self.exists(new):
                        continue
                    self.say(f'{model.__name__}.{field.name} #{pk}: {name} -> {new}')
                    self.changed += 1
                    if not self.dry_run:
                        model._base_manager.filter(pk=pk).update(**{field.attname: new})

    def update_text_links(self):
        """Fields that hold a file's /media/ URL as text (AI chat pictures and videos)."""
        from ai_app.models import AIMessage, AIUserImage, AIVideoJob, EduChatsAIMessage
        fields = [(AIMessage, 'image_data'), (AIMessage, 'video_url'), (AIUserImage, 'url'),
                  (AIVideoJob, 'video_url'), (EduChatsAIMessage, 'image_url')]
        prefixes = (settings.MEDIA_URL, 'https://www.edutrellis.in' + settings.MEDIA_URL)
        for model, field in fields:
            for prefix in prefixes:
                q = Q()
                for old, _ in media_folders.LEGACY_FOLDERS:
                    q |= Q(**{f'{field}__startswith': prefix + old})
                for pk, value in model.objects.filter(q).values_list('pk', field).iterator():
                    name = value[len(prefix):]
                    new = media_folders.new_name(name)
                    if not self.exists(new):
                        continue
                    self.say(f'link {model.__name__}.{field} #{pk}')
                    self.changed += 1
                    if not self.dry_run:
                        model.objects.filter(pk=pk).update(**{field: prefix + new})

    # ── Call recordings ────────────────────────────────────────────────────

    def move_disk_recordings(self):
        old_root = Path(settings.PRIVATE_FILES_ROOT) / 'ai_calls'
        if not old_root.is_dir():
            return
        new_root = _private_path(media_folders.AI_CALLS)
        for path in sorted(p for p in old_root.rglob('*') if p.is_file()):
            target = new_root / path.relative_to(old_root)
            self.say(f'recording {path} -> {target}')
            self.changed += 1
            if self.dry_run or target.exists():
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), str(target))
        if not self.dry_run:
            for folder in sorted((p for p in old_root.rglob('*') if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
                try:
                    folder.rmdir()
                except OSError:
                    pass
            try:
                old_root.rmdir()
            except OSError:
                pass

    def archive_recordings(self):
        from ai_app import ai_calls
        from ai_app.models import AICall
        cutoff = timezone.now() - timedelta(minutes=10)
        calls = AICall.objects.filter(ended_at__lt=cutoff, audio__startswith=media_folders.AI_CALLS)
        for pk, name in calls.values_list('pk', 'audio').iterator():
            if not _private_path(name).is_file():
                continue
            self.say(f'upload recording of call {pk}')
            self.changed += 1
            if self.dry_run:
                continue
            try:
                ai_calls.archive_recording(pk)
            except Exception as exc:
                self.failed += 1
                self.stderr.write(f'  could not upload the recording of call {pk}: {exc}')

    def say(self, text):
        if self.verbosity >= 1:
            self.stdout.write(('[dry run] ' if self.dry_run else '') + text)


def _private_path(name):
    return Path(settings.PRIVATE_FILES_ROOT) / name


def _archive_legacy_root():
    from ai_app import dropbox_images
    return dropbox_images.LEGACY_ROOT_FOLDER
