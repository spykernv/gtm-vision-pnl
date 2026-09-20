"""Copy private local data to an explicitly chosen destination and verify hashes.

No network API and no proof of cloud synchronization. Failed partial copies remain
marked .partial for inspection, never presented as a completed backup.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

sys.dont_write_bytecode = True
from gtm import ROOT, Blocked, Store, atomic, digest, mutex, read
from retention import prune_local, prune_snapshots, LOCAL_RECENT, REMOTE_RECENT, DAILY, MONTHLY


def inventory(directory, exclude_backups=False):
    directory = Path(directory)
    if directory.is_symlink() or directory.is_junction():
        raise Blocked('Backup refuses a linked root')
    result = {}
    for base, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink() or p.is_junction():
                raise Blocked('Backup refuses links and directory junctions')
        if exclude_backups and Path(base) == directory:
            dirs[:] = [d for d in dirs if d != 'backups']
        for name in files:
            p = Path(base) / name
            if p == directory / 'journal.lock':
                continue
            result[p.relative_to(directory).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def backup(root, destination):
    store = Store(root)
    source = store.local.resolve()
    destination = Path(destination).expanduser().resolve()
    if destination.is_relative_to(store.root.resolve()):
        raise Blocked('Backup destination must be outside this installation')
    with mutex(source / 'journal.lock'):
        state = read(store.path)
        revision = state['local_runtime']['revision']
        files = inventory(source, exclude_backups=True)
        if 'GTM_Design_Partners_Etat.json' not in files:
            raise Blocked('Canonical journal missing')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        name = 'gtm-' + stamp + '-' + uuid.uuid4().hex[:8]
        partial = destination / (name + '.partial')
        target = destination / name
        partial.mkdir(parents=True, exist_ok=False)
        for rel in files:
            dest = partial / 'local' / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / rel, dest)
        if inventory(partial / 'local') != files or inventory(source, exclude_backups=True) != files:
            raise Blocked('Backup verification failed or source changed; partial copy retained')
        manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                    'retention_schema': 1,
                    'installation_id': digest({'account':state['preferred_sender'], 'sources':state['local_runtime'].get('source_hashes', {})}),
                    'excluded_directories': ['backups'],
                    'retention_policy': {'local_recent':LOCAL_RECENT, 'snapshot_recent':REMOTE_RECENT, 'daily':DAILY, 'monthly':MONTHLY},
                    'revision': revision, 'file_count': len(files), 'sha256': files,
                    'verified_local_copy': True, 'cloud_sync_verified': False,
                    'restore_note': 'Pause the Desktop task, restore into an isolated installation, create local/STOP and reconcile receipts before any activation.'}
        atomic(partial / 'manifest.json', manifest)
        partial.rename(target)
        result = {'backup': str(target), 'revision': revision, 'file_count': len(files),
                  'verified_local_copy': True, 'cloud_sync_verified': False}
        # Only prune after a complete, durable, verified recovery copy exists.
        # Unresolved send ownership pins all old copies until reconciliation.
        if any(e['phase'] in {'CLAIMED', 'SENDING'} for e in state['local_runtime']['events'].values()):
            result['retention'] = {'skipped': 'unresolved_send_ownership'}
        else:
            try:
                result['retention'] = prune_snapshots(destination, target, manifest, inventory)
                result['retention']['local_backups_removed'] = prune_local(store)
            except (Blocked, OSError, ValueError, KeyError) as exc:
                result['cleanup_error'] = str(exc)
        return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--destination', type=Path)
    group.add_argument('--configured', action='store_true')
    args = p.parse_args()
    try:
        destination = args.destination
        if args.configured:
            config = read(args.root / 'local' / 'backup-config.json')
            destination = config['destination']
        result = backup(args.root, destination)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get('cleanup_error') else 0
    except (Blocked, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'blocked': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
