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
from gtm import ROOT, Blocked, Store, atomic, mutex, read


def inventory(directory):
    result = {}
    for base, dirs, files in os.walk(directory, followlinks=False):
        for name in dirs + files:
            p = Path(base) / name
            if p.is_symlink() or p.is_junction():
                raise Blocked('Backup refuses links and directory junctions')
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
        revision = read(store.path)['local_runtime']['revision']
        files = inventory(source)
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
        if inventory(partial / 'local') != files or inventory(source) != files:
            raise Blocked('Backup verification failed or source changed; partial copy retained')
        manifest = {'created_at': datetime.now(timezone.utc).isoformat(),
                    'revision': revision, 'file_count': len(files), 'sha256': files,
                    'verified_local_copy': True, 'cloud_sync_verified': False,
                    'restore_note': 'Pause the Desktop task, restore into an isolated installation, create local/STOP and reconcile receipts before any activation.'}
        atomic(partial / 'manifest.json', manifest)
        partial.rename(target)
        return {'backup': str(target), 'revision': revision, 'file_count': len(files),
                'verified_local_copy': True, 'cloud_sync_verified': False}


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
        print(json.dumps(backup(args.root, destination), ensure_ascii=False, indent=2))
        return 0
    except (Blocked, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'blocked': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
