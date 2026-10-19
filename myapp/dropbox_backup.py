"""Backs up/restores db.sqlite3 to/from a Dropbox app folder, using the
store owner's Dropbox App Key/Secret + a long-lived OAuth2 refresh token
(configured from the store dashboard). Degrades gracefully if the
`dropbox` package isn't installed or credentials aren't set yet.
"""
import datetime
import io
from pathlib import Path
import zipfile

from django.conf import settings as dj_settings

try:
    import dropbox
except ImportError:  # pragma: no cover - optional dependency until configured
    dropbox = None

BACKUP_ROOT = '/EduTrellis Store'
BACKUP_FOLDER = f'{BACKUP_ROOT}/backups'
LATEST_NAME = 'db_latest.sqlite3'
ASSETS_LATEST_NAME = 'customize_latest.zip'
ASSET_FOLDERS = ('customize', 'pwa')


class BackupError(Exception):
    """Raised for any Dropbox/backup failure with a message safe to show the admin."""


def db_path():
    return Path(dj_settings.DATABASES['default']['NAME'])


def _client(settings_obj):
    if dropbox is None:
        raise BackupError("The 'dropbox' Python package isn't installed on this server.")
    if not settings_obj.is_configured:
        raise BackupError('Dropbox is not configured yet — add your App Key, App Secret and Refresh Token first.')
    return dropbox.Dropbox(
        oauth2_refresh_token=settings_obj.effective_refresh_token,
        app_key=settings_obj.effective_app_key,
        app_secret=settings_obj.effective_app_secret,
    )


def _ensure_folder(dbx, path):
    try:
        dbx.files_create_folder_v2(path)
    except Exception as exc:
        if 'conflict' not in str(exc).lower():  # folder already exists — fine
            raise BackupError(f"Could not create the Dropbox folder '{path}': {exc}")


def _customization_archive():
    """Returns a ZIP containing uploaded customization and PWA images."""
    media_root = Path(dj_settings.MEDIA_ROOT).resolve()
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode='w', compression=zipfile.ZIP_DEFLATED) as archive:
        for folder_name in ASSET_FOLDERS:
            folder = (media_root / folder_name).resolve()
            if not folder.is_dir() or media_root not in folder.parents:
                continue
            for path in folder.rglob('*'):
                resolved = path.resolve()
                if path.is_file() and media_root in resolved.parents:
                    archive.write(resolved, resolved.relative_to(media_root).as_posix())
    return output.getvalue()


def _asset_backup_name(database_filename):
    if database_filename == LATEST_NAME:
        return ASSETS_LATEST_NAME
    if database_filename.startswith('db_') and database_filename.endswith('.sqlite3'):
        stamp = database_filename[len('db_'):-len('.sqlite3')]
        return f'customize_{stamp}.zip'
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
    """Safely restores archived media files without deleting unrelated media."""
    if content is None:
        return False
    media_root = Path(dj_settings.MEDIA_ROOT).resolve()
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            for item in archive.infolist():
                if item.is_dir():
                    continue
                target = (media_root / item.filename).resolve()
                if media_root not in target.parents:
                    raise BackupError('Customization backup contains an unsafe file path.')
                target.parent.mkdir(parents=True, exist_ok=True)
                temporary = target.with_suffix(target.suffix + '.restoring')
                temporary.write_bytes(archive.read(item))
                temporary.replace(target)
        return True
    except BackupError:
        raise
    except (OSError, zipfile.BadZipFile) as exc:
        raise BackupError(f'Could not restore customization images: {exc}')


def create_backup(settings_obj):
    """Uploads paired database and customization-image backups."""
    try:
        dbx = _client(settings_obj)
        _ensure_folder(dbx, BACKUP_ROOT)
        _ensure_folder(dbx, BACKUP_FOLDER)

        path = db_path()
        if not path.exists():
            raise BackupError('Local database file was not found.')
        data = path.read_bytes()

        stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'db_{stamp}.sqlite3'
        asset_filename = f'customize_{stamp}.zip'
        asset_data = _customization_archive()
        dbx.files_upload(data, f'{BACKUP_FOLDER}/{filename}', mode=dropbox.files.WriteMode.add)
        dbx.files_upload(data, f'{BACKUP_FOLDER}/{LATEST_NAME}', mode=dropbox.files.WriteMode.overwrite)
        dbx.files_upload(asset_data, f'{BACKUP_FOLDER}/{asset_filename}', mode=dropbox.files.WriteMode.add)
        dbx.files_upload(asset_data, f'{BACKUP_FOLDER}/{ASSETS_LATEST_NAME}', mode=dropbox.files.WriteMode.overwrite)
        return filename
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f'Backup to Dropbox failed: {exc}')


def list_backups(settings_obj):
    """Returns timestamped backup files (newest first), excluding db_latest.sqlite3."""
    try:
        dbx = _client(settings_obj)
        try:
            res = dbx.files_list_folder(BACKUP_FOLDER)
        except Exception as exc:
            if 'not_found' in str(exc).lower():
                return []
            raise

        entries = list(res.entries)
        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            entries.extend(res.entries)

        files = [
            e for e in entries
            if isinstance(e, dropbox.files.FileMetadata)
            and e.name.startswith('db_') and e.name.endswith('.sqlite3')
            and e.name != LATEST_NAME
        ]
        files.sort(key=lambda e: e.name, reverse=True)
        return files
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f'Could not list Dropbox backups: {exc}')


def _is_backup_file(name):
    return ((name.startswith('db_') and name.endswith('.sqlite3'))
            or (name.startswith('customize_') and name.endswith('.zip')))


def delete_all_backups(settings_obj):
    """Deletes every backup in the backups folder: the timestamped database and
    image copies and the db_latest / customize_latest ones. Returns (database
    backups removed, files removed). Nothing else in the Dropbox app folder is touched."""
    import time
    try:
        dbx = _client(settings_obj)
        try:
            res = dbx.files_list_folder(BACKUP_FOLDER)
        except Exception as exc:
            if 'not_found' in str(exc).lower():
                return 0, 0
            raise
        entries = list(res.entries)
        while res.has_more:
            res = dbx.files_list_folder_continue(res.cursor)
            entries.extend(res.entries)
        files = [e for e in entries if isinstance(e, dropbox.files.FileMetadata) and _is_backup_file(e.name)]
        if not files:
            return 0, 0
        databases = sum(1 for e in files if e.name.endswith('.sqlite3') and e.name != LATEST_NAME)
        for start in range(0, len(files), 1000):   # Dropbox takes up to 1000 per batch
            batch = [dropbox.files.DeleteArg(e.path_lower) for e in files[start:start + 1000]]
            job = dbx.files_delete_batch_v2(batch)
            if job.is_async_job_id():
                job_id = job.get_async_job_id()
                for _ in range(60):
                    status = dbx.files_delete_batch_check(job_id)
                    if status.is_complete():
                        break
                    if status.is_failed():
                        raise BackupError('Dropbox could not delete the backups. Please try again.')
                    time.sleep(1)
                else:
                    raise BackupError('Dropbox is still deleting the backups. Refresh this page in a minute.')
        return databases, len(files)
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f'Could not delete the Dropbox backups: {exc}')


def restore_backup(settings_obj, filename):
    """Restores the database and its paired customization-image archive."""
    if not filename or '/' in filename or '\\' in filename:
        raise BackupError('Invalid backup filename.')

    try:
        dbx = _client(settings_obj)
        _, resp = dbx.files_download(f'{BACKUP_FOLDER}/{filename}')
        content = resp.content
        asset_filename = _asset_backup_name(filename)
        asset_content = _download_optional(dbx, f'{BACKUP_FOLDER}/{asset_filename}') if asset_filename else None
    except BackupError:
        raise
    except Exception as exc:
        raise BackupError(f'Could not download that backup from Dropbox: {exc}')

    from django.db import connections
    connections.close_all()

    path = db_path()
    tmp_path = path.with_suffix(path.suffix + '.restoring')
    try:
        tmp_path.write_bytes(content)
        tmp_path.replace(path)
        _restore_customization_archive(asset_content)
    except OSError as exc:
        raise BackupError(
            f'Could not write the restored database (it may be locked by the running server): {exc}'
        )
