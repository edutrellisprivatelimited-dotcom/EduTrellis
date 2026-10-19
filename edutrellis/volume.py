"""Railway volume: keeps the database and uploaded files across redeploys.

On Railway a persistent disk is attached to the web service and its folder is in
RAILWAY_VOLUME_MOUNT_PATH (EduTrellis: /media). settings.py then keeps

    <volume>/data/db.sqlite3   the database (never served to the web)
    <volume>/uploads/          MEDIA_ROOT — everything served at /media/...

The first time the app starts on an empty volume, prepare() copies the database
that came with the code onto it; on every start it adds files that ship with the
code (in media/) and aren't on the volume yet. It never overwrites anything already
on the volume: from then on the volume is the live copy. Dropbox backup and restore
keep working as before — they follow settings.DATABASES / MEDIA_ROOT.
"""
import logging
import shutil
import sqlite3
from pathlib import Path

log = logging.getLogger(__name__)

SKIP = {'ai_youtube'}   # temporary downloads, never worth keeping


def _copy_database(seed, target):
    """A consistent copy through SQLite's backup API (safe even with a -wal file next to it)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + '.copying')
    src, dst = sqlite3.connect(str(seed)), sqlite3.connect(str(tmp))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    tmp.replace(target)


def _copy_missing_files(source, target):
    copied = 0
    for path in source.rglob('*'):
        rel = path.relative_to(source)
        if not path.is_file() or (rel.parts and rel.parts[0] in SKIP):
            continue
        dest = target / rel
        if dest.exists():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        copied += 1
    return copied


def prepare(base_dir, db_file, media_dir):
    base_dir, db_file, media_dir = Path(base_dir), Path(db_file), Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    seed = base_dir / 'db.sqlite3'
    if not db_file.exists() and seed.exists():
        _copy_database(seed, db_file)   # a failure here stops the start: better than an empty site
        log.warning('Railway volume: database copied to %s', db_file)
    try:
        n = _copy_missing_files(base_dir / 'media', media_dir) if (base_dir / 'media').is_dir() else 0
        if n:
            log.warning('Railway volume: %d media files copied to %s', n, media_dir)
    except OSError as exc:   # a missing picture is not worth refusing to start over
        log.warning('Railway volume: could not copy some media files: %s', exc)
