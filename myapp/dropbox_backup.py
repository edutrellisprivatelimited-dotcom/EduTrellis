"""Backs up/restores the SQLite database to/from Dropbox, using the store
owner's Dropbox App Key/Secret + a long-lived OAuth2 refresh token
(Dashboard → Backup & Restore → Settings). Uploaded images and files are not
part of a backup: they already live in Dropbox ('/EduTrellis Site', see
dropbox_storage).

Backups are named after the brand and the local date and time, by kind:

    EduTrellis_Backup_2026-11-14_10-30-15.sqlite3          Backup Now
    EduTrellis_AutoBackup_2026-11-14_03-00-02.sqlite3      automatic (auto_backup.py)
    EduTrellis_BeforeRestore_2026-11-14_11-02-40.sqlite3   safety copy taken before a restore
    EduTrellis_Uploaded_2026-11-14_11-05-09.sqlite3        a database file uploaded from the dashboard

plus EduTrellis_Latest.sqlite3, always the newest copy. Older backups named
db_<stamp>.sqlite3 keep working. Degrades gracefully if the `dropbox`
package isn't installed or credentials aren't set yet.
"""
import datetime
import functools
import hashlib
import io
import os
import re
import sqlite3
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from django.conf import settings as dj_settings

try:
    import dropbox
except ImportError:  # pragma: no cover - optional dependency until configured
    dropbox = None

BRAND = 'EduTrellis'
DEFAULT_FOLDER = '/EduTrellis Store/backups'
LATEST_NAME = f'{BRAND}_Latest.sqlite3'
LEGACY_LATEST_NAME = 'db_latest.sqlite3'
ASSETS_LATEST_NAME = 'customize_latest.zip'

KIND_MANUAL, KIND_AUTO, KIND_SAFETY, KIND_UPLOAD = 'manual', 'auto', 'before_restore', 'upload'
KIND_WORDS = {KIND_MANUAL: 'Backup', KIND_AUTO: 'AutoBackup', KIND_SAFETY: 'BeforeRestore', KIND_UPLOAD: 'Uploaded'}
KIND_LABELS = {KIND_MANUAL: 'Manual', KIND_AUTO: 'Automatic', KIND_SAFETY: 'Before restore', KIND_UPLOAD: 'Uploaded'}
_WORD_KINDS = {word: kind for kind, word in KIND_WORDS.items()}
_NAME_RE = re.compile(rf'{BRAND}_({"|".join(KIND_WORDS.values())})_(\d{{4}}-\d{{2}}-\d{{2}})_(\d{{2}})-(\d{{2}})-(\d{{2}})(?:_\d+)?\.sqlite3\Z')
LEGACY_SAFETY_SUFFIX = '_before_restore'

UPLOAD_CHUNK = 8 * 1024 * 1024
SINGLE_UPLOAD_LIMIT = 140 * 1024 * 1024   # Dropbox's one-shot upload limit is 150 MB
MAX_UPLOADED_DATABASE = 500 * 1024 * 1024


class BackupError(Exception):
    """Raised for any Dropbox/backup failure with a message safe to show the admin."""


def db_path():
    return Path(dj_settings.DATABASES['default']['NAME'])


# ── Names and folders ──────────────────────────────────────────────────────

def backup_filename(kind, when=None):
    from django.utils import timezone
    when = timezone.localtime(when or timezone.now())
    return f'{BRAND}_{KIND_WORDS[kind]}_{when:%Y-%m-%d_%H-%M-%S}.sqlite3'


def is_backup_name(name):
    """A restorable database backup (not the 'latest' copy)."""
    if not name or '/' in name or '\\' in name or name in (LATEST_NAME, LEGACY_LATEST_NAME):
        return False
    return bool(_NAME_RE.match(name)) or (name.startswith('db_') and name.endswith('.sqlite3'))


def kind_of(name):
    m = _NAME_RE.match(name)
    if m:
        return _WORD_KINDS[m.group(1)]
    return KIND_SAFETY if name.endswith(LEGACY_SAFETY_SUFFIX + '.sqlite3') else KIND_MANUAL


def clean_folder(path):
    """'/Some Folder/backups' — or BackupError for anything that isn't a plain Dropbox folder path."""
    path = (path or '').strip().replace('\\', '/')
    if not path.startswith('/'):
        path = '/' + path
    path = re.sub(r'/{2,}', '/', path).rstrip('/')
    parts = path.split('/')[1:]
    if not parts or any(p in ('', '.', '..') or p != p.strip() or p.endswith('.') for p in parts):
        raise BackupError('Enter a Dropbox folder path such as /EduTrellis Store/backups.')
    if len(path) > 200 or re.search(r'[<>:"|?*\x00-\x1f]', path):
        raise BackupError('That folder name has characters Dropbox does not allow.')
    media_root = getattr(dj_settings, 'DROPBOX_MEDIA_ROOT', '/EduTrellis Site').rstrip('/').lower()
    if path.lower() == media_root or path.lower().startswith(media_root + '/'):
        raise BackupError(f'Keep backups outside {media_root} — that folder holds the website\'s uploaded files.')
    return path


def folder(settings_obj):
    try:
        return clean_folder(getattr(settings_obj, 'backup_folder', '') or DEFAULT_FOLDER)
    except BackupError:
        return DEFAULT_FOLDER


def _client(settings_obj):
    if dropbox is None:
        raise BackupError("The 'dropbox' Python package isn't installed on this server.")
    if not settings_obj.is_configured:
        raise BackupError('Dropbox is not configured yet — add your App Key, App Secret and Refresh Token first.')
    return dropbox.Dropbox(
        oauth2_refresh_token=settings_obj.effective_refresh_token,
        app_key=settings_obj.effective_app_key,
        app_secret=settings_obj.effective_app_secret,
        timeout=120,
    )


def _ensure_folder(dbx, path):
    """Creates the folder and any missing parents."""
    try:
        dbx.files_create_folder_v2(path)
    except Exception as exc:
        if 'conflict' not in str(exc).lower():  # folder already exists — fine
            raise BackupError(f"Could not create the Dropbox folder '{path}': {exc}")


# ── Connection status ──────────────────────────────────────────────────────

_status_cache = {}


def connection_info(settings_obj, fresh=False):
    """{'ok', 'name', 'email', 'used', 'allocated', 'error'} for the dashboard.
    Cached for a minute so the page doesn't wait on Dropbox every time."""
    key = (settings_obj.effective_app_key, settings_obj.effective_refresh_token[-12:])
    cached = _status_cache.get(key)
    if cached and not fresh and time.monotonic() - cached[0] < 60:
        return cached[1]
    info = {'ok': False, 'name': '', 'email': '', 'used': None, 'allocated': None, 'error': ''}
    try:
        dbx = _client(settings_obj)
        try:
            account = dbx.users_get_current_account()
            info.update(name=account.name.display_name, email=account.email)
            space = dbx.users_get_space_usage()
            info['used'] = space.used
            if space.allocation.is_individual():
                info['allocated'] = space.allocation.get_individual().allocated
            elif space.allocation.is_team():
                info['allocated'] = space.allocation.get_team().allocated
        except dropbox.exceptions.AuthError:
            # The app may not have the account_info.read permission; a file
            # call still proves the connection works.
            dbx.files_list_folder('', limit=1)
        info['ok'] = True
    except BackupError as exc:
        info['error'] = str(exc)
    except Exception as exc:
        text = str(exc)
        info['error'] = ('Dropbox refused the saved credentials — check the App Key, App Secret and Refresh Token.'
                         if 'invalid_grant' in text or 'AuthError' in type(exc).__name__ else f'Could not reach Dropbox: {text[:200]}')
    _status_cache[key] = (time.monotonic(), info)
    return info


# ── Backup files ───────────────────────────────────────────────────────────

class BackupFile:
    """One database backup as the dashboard shows it."""

    def __init__(self, meta):
        from django.utils import timezone
        self.name = meta.name
        self.size = meta.size or 0
        self.kind = kind_of(meta.name)
        self.kind_label = KIND_LABELS[self.kind]
        self.safety = self.kind == KIND_SAFETY
        modified = meta.client_modified
        if modified is not None:
            if timezone.is_naive(modified):   # Dropbox reports UTC
                modified = modified.replace(tzinfo=datetime.timezone.utc)
            modified = timezone.localtime(modified)
        self.modified = modified


# Backups, restores and deletes never run at the same time (a double click, two
# admins, the automatic backup): one would read or replace the database while
# the other is using it.
_busy = threading.Lock()


def _one_at_a_time(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not _busy.acquire(blocking=False):
            raise BackupError('Another backup, restore or delete is already running. Wait for it to finish and try again.')
        try:
            return fn(*args, **kwargs)
        finally:
            _busy.release()
    return wrapper


def _content_hash(data):
    """Dropbox's content_hash: SHA-256 of the SHA-256s of each 4 MB block."""
    blocks = b''.join(hashlib.sha256(data[i:i + 4194304]).digest() for i in range(0, len(data), 4194304))
    return hashlib.sha256(blocks).hexdigest()


def _upload(dbx, data, path, overwrite=False):
    """Uploads and checks that Dropbox stored exactly these bytes."""
    mode = dropbox.files.WriteMode.overwrite if overwrite else dropbox.files.WriteMode.add
    if len(data) <= SINGLE_UPLOAD_LIMIT:
        meta = dbx.files_upload(data, path, mode=mode, autorename=not overwrite)
    else:
        session = dbx.files_upload_session_start(data[:UPLOAD_CHUNK])
        offset = UPLOAD_CHUNK
        while len(data) - offset > UPLOAD_CHUNK:
            cursor = dropbox.files.UploadSessionCursor(session_id=session.session_id, offset=offset)
            dbx.files_upload_session_append_v2(data[offset:offset + UPLOAD_CHUNK], cursor)
            offset += UPLOAD_CHUNK
        cursor = dropbox.files.UploadSessionCursor(session_id=session.session_id, offset=offset)
        commit = dropbox.files.CommitInfo(path=path, mode=mode, autorename=not overwrite)
        meta = dbx.files_upload_session_finish(data[offset:], cursor, commit)
    expected = _content_hash(data)
    if getattr(meta, 'content_hash', expected) != expected:
        raise BackupError(f'Dropbox stored a damaged copy of {path.rsplit("/", 1)[-1]}. Please try again.')
    return meta


def _check_database_file(path):
    """Raises BackupError unless `path` is a healthy SQLite database of this site."""
    with open(path, 'rb') as fh:
        if fh.read(16) != b'SQLite format 3\x00':
            raise BackupError('That file is not an SQLite database.')
    try:
        conn = sqlite3.connect(f'file:{Path(path).as_posix()}?mode=ro', uri=True)
        try:
            result = conn.execute('PRAGMA integrity_check').fetchall()
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise BackupError(f'That database file is damaged: {exc}')
    if result != [('ok',)]:
        raise BackupError('That database file is damaged.')
    if not {'django_migrations', 'auth_user', 'django_session'} <= tables:
        raise BackupError("That file isn't an EduTrellis database.")


def _temp_path(suffix):
    fd, name = tempfile.mkstemp(prefix='.backup-', suffix=suffix, dir=db_path().parent)
    os.close(fd)
    return Path(name)


def snapshot_database():
    """A consistent, compacted copy of the live database as bytes. SQLite
    copies it inside one read transaction, so a write landing halfway through
    can't leave a half-old, half-new (corrupt) file the way copying the bytes
    can; VACUUM INTO also leaves out free pages, which keeps uploads small."""
    path = db_path()
    if not path.exists():
        raise BackupError('Local database file was not found.')
    snapshot = _temp_path('.sqlite3')
    try:
        src = sqlite3.connect(str(path), timeout=30)
        try:
            snapshot.unlink()
            src.execute('VACUUM INTO ?', (str(snapshot),))
        except sqlite3.OperationalError:   # SQLite older than 3.27
            snapshot.touch()
            dst = sqlite3.connect(str(snapshot))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        _check_database_file(snapshot)
        return snapshot.read_bytes()
    except sqlite3.Error as exc:
        raise BackupError(f'Could not read the live database: {exc}')
    finally:
        snapshot.unlink(missing_ok=True)


def _store(dbx, settings_obj, data, kind, refresh_latest=True):
    """Uploads database bytes as a new backup; returns its file name."""
    target = folder(settings_obj)
    _ensure_folder(dbx, target)
    meta = _upload(dbx, data, f'{target}/{backup_filename(kind)}')
    if refresh_latest:
        _upload(dbx, data, f'{target}/{LATEST_NAME}', overwrite=True)
    return meta.name


def _fail(action, exc):
    if isinstance(exc, BackupError):
        return exc
    return BackupError(f'{action} failed: {exc}')


@_one_at_a_time
def create_backup(settings_obj, kind=KIND_MANUAL):
    """Uploads a backup of the live database; returns its file name."""
    try:
        return _store(_client(settings_obj), settings_obj, snapshot_database(), kind)
    except Exception as exc:
        raise _fail('Backup to Dropbox', exc)


def _list_folder(dbx, path):
    try:
        res = dbx.files_list_folder(path)
    except Exception as exc:
        if 'not_found' in str(exc).lower():
            return []
        raise
    entries = list(res.entries)
    while res.has_more:
        res = dbx.files_list_folder_continue(res.cursor)
        entries.extend(res.entries)
    return [e for e in entries if isinstance(e, dropbox.files.FileMetadata)]


def list_backups(settings_obj):
    """Restorable backups, newest first."""
    try:
        files = [BackupFile(e) for e in _list_folder(_client(settings_obj), folder(settings_obj)) if is_backup_name(e.name)]
    except Exception as exc:
        raise _fail('Listing the Dropbox backups', exc)
    epoch = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    files.sort(key=lambda f: (f.modified or epoch, f.name), reverse=True)
    return files


def _check_name(filename):
    if not is_backup_name(filename):
        raise BackupError('Invalid backup filename.')


def download_backup(settings_obj, filename):
    """(chunks iterator, size) for streaming one backup to the browser."""
    _check_name(filename)
    try:
        meta, resp = _client(settings_obj).files_download(f'{folder(settings_obj)}/{filename}')
    except Exception as exc:
        if 'not_found' in str(exc).lower():
            raise BackupError(f'{filename} is no longer on Dropbox.')
        raise _fail('Downloading the backup', exc)

    def chunks():
        try:
            yield from resp.iter_content(64 * 1024)
        finally:
            resp.close()
    return chunks(), meta.size


def _is_backup_file(name):
    return (is_backup_name(name) or name in (LATEST_NAME, LEGACY_LATEST_NAME)
            or (name.startswith('customize_') and name.endswith('.zip')))


def _delete_paths(dbx, paths):
    for start in range(0, len(paths), 1000):   # Dropbox takes up to 1000 per batch
        job = dbx.files_delete_batch([dropbox.files.DeleteArg(p) for p in paths[start:start + 1000]])
        if job.is_async_job_id():
            job_id = job.get_async_job_id()
            for _ in range(60):
                job = dbx.files_delete_batch_check(job_id)
                if not job.is_in_progress():
                    break
                time.sleep(1)
            else:
                raise BackupError('Dropbox is still deleting the backups. Refresh this page in a minute.')
        if not job.is_complete():
            raise BackupError('Dropbox could not delete the backups. Please try again.')
        failed = [r for r in job.get_complete().entries if r.is_failure()]
        if failed:
            raise BackupError(f'Dropbox could not delete {len(failed)} of the backup files. Please try again.')


@_one_at_a_time
def delete_backup(settings_obj, filename):
    """Deletes one backup (and the image archive older backups came with)."""
    _check_name(filename)
    try:
        dbx = _client(settings_obj)
        base = folder(settings_obj)
        dbx.files_delete_v2(f'{base}/{filename}')
        asset = _asset_backup_name(filename)
        if asset:
            try:
                dbx.files_delete_v2(f'{base}/{asset}')
            except Exception:
                pass
    except Exception as exc:
        if 'not_found' in str(exc).lower():
            return
        raise _fail('Deleting the backup', exc)


@_one_at_a_time
def delete_all_backups(settings_obj):
    """Deletes every backup in the backups folder, including the latest copies
    and older image archives. Returns (database backups removed, files removed).
    Nothing else in Dropbox is touched."""
    try:
        dbx = _client(settings_obj)
        files = [e for e in _list_folder(dbx, folder(settings_obj)) if _is_backup_file(e.name)]
        if files:
            _delete_paths(dbx, [e.path_lower for e in files])
        return sum(1 for e in files if is_backup_name(e.name)), len(files)
    except Exception as exc:
        raise _fail('Deleting the Dropbox backups', exc)


def prune_auto_backups(settings_obj, keep):
    """Deletes automatic backups beyond the newest `keep`. Returns how many went."""
    try:
        dbx = _client(settings_obj)
        autos = sorted((e for e in _list_folder(dbx, folder(settings_obj)) if kind_of(e.name) == KIND_AUTO
                        and is_backup_name(e.name)), key=lambda e: e.name, reverse=True)
        old = autos[max(keep, 1):]
        if old:
            _delete_paths(dbx, [e.path_lower for e in old])
        return len(old)
    except Exception as exc:
        raise _fail('Removing old automatic backups', exc)


@_one_at_a_time
def move_folder(settings_obj, old, new):
    """Moves the backups from one Dropbox folder to another. Returns how many files moved."""
    old, new = clean_folder(old), clean_folder(new)
    if old.lower() == new.lower():
        return 0
    try:
        dbx = _client(settings_obj)
        files = [e for e in _list_folder(dbx, old) if _is_backup_file(e.name)]
        if not files:
            return 0
        _ensure_folder(dbx, new)
        for e in files:
            dbx.files_move_v2(e.path_lower, f'{new}/{e.name}', autorename=True)
        return len(files)
    except Exception as exc:
        raise _fail('Moving the backups', exc)


# ── Restore ────────────────────────────────────────────────────────────────

def _asset_backup_name(database_filename):
    if database_filename == LEGACY_LATEST_NAME:
        return ASSETS_LATEST_NAME
    if database_filename.startswith('db_') and database_filename.endswith('.sqlite3'):
        return f'customize_{database_filename[len("db_"):-len(".sqlite3")]}.zip'
    return None


def _download_optional(dbx, path):
    try:
        _, response = dbx.files_download(path)
        return response.content
    except Exception as exc:
        if 'not_found' in str(exc).lower():
            return None
        raise


def _restore_customization_archive(content):
    """Older backups carry a zip of the customization/PWA images. Images now
    live in Dropbox, so any of them that are missing there are put back."""
    if content is None:
        return False
    from . import dropbox_storage
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                if not dropbox_storage.is_safe_name(item.filename):
                    raise BackupError('Customization backup contains an unsafe file path.')
                if not dropbox_storage.DropboxStorage().exists(item.filename):
                    dropbox_storage.store_existing(item.filename, archive.read(item))
        return True
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f'Could not restore customization images: {exc}')


def _copy_database(source, target):
    """Copies one SQLite database over another through SQLite itself, so the
    live file is replaced under SQLite's own locks: requests running at the
    same moment wait instead of reading a half-written file."""
    src = sqlite3.connect(str(source), timeout=30)
    dst = sqlite3.connect(str(target), timeout=30)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def _migrate():
    """Brings an older backup up to the current tables (new features added
    since it was taken), exactly like a deploy does."""
    from django.core.management import call_command
    from django.db import connections
    connections.close_all()
    call_command('migrate', interactive=False, verbosity=0)
    connections.close_all()


_KEPT_SETTINGS = ('app_key', 'app_secret', 'refresh_token', 'backup_folder', 'auto_backup_enabled',
                  'auto_backup_every_hours', 'auto_backup_keep', 'last_auto_backup_at', 'last_auto_backup_error')


def _keep_dropbox_settings(saved):
    """A restored backup holds the Dropbox settings of its own day; put back
    the ones in use now, so a restore never disconnects Dropbox or moves the
    backup folder."""
    from .models import DropboxSettings
    DropboxSettings.objects.update_or_create(pk=1, defaults=saved)
    _status_cache.clear()
    try:
        from ai_app import dropbox_images
        dropbox_images.reset_credentials()
    except Exception:
        pass


def _restore_file(dbx, settings_obj, incoming, label, asset_content=None):
    """Swaps the database at `incoming` in. Safe order: check the file is a
    healthy EduTrellis database → save the current data to Dropbox as a
    BeforeRestore backup → swap → update its tables. If any step fails the
    live data is left as it was (or put back). Returns the safety copy's name."""
    from django.db import connections
    try:
        _check_database_file(incoming)
    except BackupError as exc:
        raise BackupError(f"{label} can't be restored: {exc} Nothing was changed.")
    if asset_content is not None:
        try:
            zipfile.ZipFile(io.BytesIO(asset_content)).testzip()
        except zipfile.BadZipFile:
            asset_content = None   # restore the data anyway; keep the current images

    saved = {f: getattr(settings_obj, f) for f in _KEPT_SETTINGS}
    current = _temp_path('.sqlite3')
    try:
        connections.close_all()
        _copy_database(db_path(), current)
        try:
            safety = _store(dbx, settings_obj, snapshot_database(), KIND_SAFETY, refresh_latest=False)
        except Exception as exc:
            raise BackupError(f'Restore cancelled — could not save a safety copy of the current data first ({exc}). Nothing was changed.')
        try:
            _copy_database(incoming, db_path())
            _migrate()
        except Exception as exc:
            try:
                _copy_database(current, db_path())
                connections.close_all()
            except Exception as undo_exc:
                raise BackupError(f'Restore failed ({exc}) and the previous data could not be put back automatically '
                                  f'({undo_exc}). Restore {safety} to get it back.')
            raise BackupError(f'Restore failed and was undone — your data is as it was. ({exc})')
        _keep_dropbox_settings(saved)
        _restore_customization_archive(asset_content)
        return safety
    finally:
        current.unlink(missing_ok=True)


@_one_at_a_time
def restore_backup(settings_obj, filename):
    """Restores one backup from the Dropbox folder. Returns the safety copy's name."""
    _check_name(filename)
    try:
        dbx = _client(settings_obj)
        base = folder(settings_obj)
        meta, resp = dbx.files_download(f'{base}/{filename}')
        content = resp.content
        asset_filename = _asset_backup_name(filename)
        asset_content = _download_optional(dbx, f'{base}/{asset_filename}') if asset_filename else None
    except Exception as exc:
        raise _fail('Downloading that backup from Dropbox', exc)
    if getattr(meta, 'content_hash', None) and meta.content_hash != _content_hash(content):
        raise BackupError('The backup came down from Dropbox incomplete. Nothing was changed — please try again.')
    incoming = _temp_path('.sqlite3')
    try:
        incoming.write_bytes(content)
        return _restore_file(dbx, settings_obj, incoming, filename, asset_content)
    except Exception as exc:
        raise _fail('Restore', exc)
    finally:
        incoming.unlink(missing_ok=True)


@_one_at_a_time
def upload_database(settings_obj, uploaded, restore=False):
    """A database file uploaded from the dashboard: checked, saved to the
    Dropbox backups as EduTrellis_Uploaded_…, and restored when asked.
    Returns (stored name, safety copy name or None)."""
    if uploaded.size > MAX_UPLOADED_DATABASE:
        raise BackupError('That file is too large (500 MB at most).')
    incoming = _temp_path('.sqlite3')
    try:
        with open(incoming, 'wb') as fh:
            for chunk in uploaded.chunks():
                fh.write(chunk)
        try:
            _check_database_file(incoming)
        except BackupError as exc:
            raise BackupError(f'{uploaded.name}: {exc} Nothing was changed.')
        dbx = _client(settings_obj)
        stored = _store(dbx, settings_obj, incoming.read_bytes(), KIND_UPLOAD, refresh_latest=False)
        safety = _restore_file(dbx, settings_obj, incoming, uploaded.name) if restore else None
        return stored, safety
    except Exception as exc:
        raise _fail('Uploading the database', exc)
    finally:
        incoming.unlink(missing_ok=True)
