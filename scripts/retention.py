"""Conservative retention of verified copies; business evidence is never aged out."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil

from gtm import Blocked, read

LOCAL_RECENT = 48
REMOTE_RECENT = 24
DAILY = 30
MONTHLY = 12


def retained(records, recent, daily=DAILY, monthly=MONTHLY):
    """Union: newest N, newest per last D distinct days, newest per M months."""
    ordered = sorted(records, key=lambda row: (row[1], str(row[0])), reverse=True)
    keep = {path for path, _ in ordered[:recent]}
    days, months = set(), set()
    for path, stamp in ordered:
        day, month = stamp.date(), (stamp.year, stamp.month)
        if day not in days and len(days) < daily:
            days.add(day)
            keep.add(path)
        if month not in months and len(months) < monthly:
            months.add(month)
            keep.add(path)
    return keep


def checked_child(path, parent):
    """Do not follow reparse points or allow any deletion outside the chosen root."""
    path, parent = Path(path), Path(parent).resolve()
    if path.is_symlink() or path.is_junction() or path.resolve().parent != parent:
        raise Blocked('Unsafe retention path')
    return path.resolve()


def prune_local(store):
    parent = store.local / 'backups'
    if not parent.exists():
        return 0
    if parent.is_symlink() or parent.is_junction() or parent.resolve().parent != store.local.resolve():
        raise Blocked('Unsafe local backup directory')
    records = []
    for path in parent.iterdir():
        if not re.fullmatch(r'journal-[0-9a-f]{32}\.json', path.name):
            continue  # Manual snapshots and unknown files are preserved.
        checked_child(path, parent)
        state = read(path)
        raw = state['local_runtime'].get('updated_at')
        stamp = datetime.fromisoformat(raw) if raw else datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        if stamp.tzinfo is None:
            raise Blocked('Backup timestamp requires timezone')
        records.append((path, stamp.astimezone(timezone.utc)))
    keep = retained(records, LOCAL_RECENT)
    removed = 0
    for path, _ in records:
        if path not in keep:
            checked_child(path, parent).unlink()
            removed += 1
    return removed


def prune_snapshots(destination, fresh, manifest, inventory):
    records = []
    manifests = {}
    for path in destination.iterdir():
        if not re.fullmatch(r'gtm-\d{8}T\d{6}Z-[0-9a-f]{8}', path.name):
            continue  # Never touch .partial, foreign files, or other directory names.
        checked_child(path, destination)
        mp = path / 'manifest.json'
        if not mp.is_file() or mp.is_symlink():
            continue
        old = read(mp)
        if old.get('retention_schema') != 1 or old.get('installation_id') != manifest['installation_id']:
            continue  # Pre-policy / foreign snapshots are not automatically adopted.
        stamp = datetime.fromisoformat(old['created_at'])
        if stamp.tzinfo is None:
            raise Blocked('Snapshot timestamp requires timezone')
        records.append((path, stamp.astimezone(timezone.utc)))
        manifests[path] = old
    keep = retained(records, REMOTE_RECENT) | {fresh}
    removed, protected = 0, 0
    for path, _ in records:
        if path in keep:
            continue
        old = manifests[path]
        # Any missing or changed immutable evidence pins the older snapshot.
        mutable = {'GTM_Design_Partners_Etat.json', 'evidence/STATUS.md', 'STOP'}
        if any(rel not in mutable and manifest['sha256'].get(rel) != sha for rel, sha in old['sha256'].items()):
            protected += 1
            continue
        if inventory(path / 'local') != old['sha256']:
            raise Blocked('Old snapshot verification failed; keep it for investigation')
        # Reject every link, including paths outside local/ and injected top-level files.
        allowed = {path / 'manifest.json', path / 'local'}
        if set(path.iterdir()) != allowed:
            raise Blocked('Unexpected snapshot contents; cleanup refused')
        checked_child(path, destination)
        shutil.rmtree(path.resolve())
        removed += 1
    return {'snapshots_removed': removed, 'snapshots_pinned': protected}
