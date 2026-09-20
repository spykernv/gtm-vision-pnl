import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_runtime as fixtures
from gtm import Blocked, atomic, read
from backup_local import backup, inventory
from status_view import build


class MaintenanceTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp

    def test_backup_verifies_all_files_and_preserves_source(self):
        self.store.sync()
        with tempfile.TemporaryDirectory() as destination:
            before = inventory(self.store.local)
            result = backup(self.store.root, destination)
            copied = Path(result['backup'])
            self.assertEqual(inventory(copied / 'local'), before)
            self.assertEqual(inventory(self.store.local), before)
            self.assertEqual(read(copied / 'manifest.json')['sha256'], before)
            self.assertFalse(result['cloud_sync_verified'])
            second = backup(self.store.root, destination)
            self.assertNotEqual(result['backup'], second['backup'])

    def test_backup_rejects_recursive_destination(self):
        with self.assertRaises(Blocked):
            backup(self.store.root, self.store.local / 'copy')
        self.assertFalse((self.store.local / 'copy').exists())

    def test_corrupted_backup_never_becomes_completed(self):
        with tempfile.TemporaryDirectory() as destination:
            original = shutil.copy2
            def corrupt(src, dst):
                original(src, dst)
                Path(dst).write_bytes(b'corrupt')
            with patch('backup_local.shutil.copy2', side_effect=corrupt):
                with self.assertRaises(Blocked):
                    backup(self.store.root, destination)
            copies = list(Path(destination).iterdir())
            self.assertTrue(copies)
            self.assertTrue(all(p.name.endswith('.partial') for p in copies))
            self.assertTrue(all(not (p / 'manifest.json').exists() for p in copies))

    def test_status_view_observes_scheduler_and_emergency_stop(self):
        self.store.sync()
        config = self.store.root / 'automation.toml'
        config.write_text('status = "PAUSED"\n', encoding='utf-8')
        result = build(self.store.root, config)
        self.assertEqual(result['scheduler'], 'PAUSED')
        self.assertEqual(build(self.store.root)['scheduler'], 'NON VÉRIFIÉ')
        self.store.mode('stop')
        result = build(self.store.root, config)
        self.assertIn('suspendues', result['patches']['Reponses']['B5'])
        self.assertIn('paused', result['patches']['Reponses']['B4'])


class CommitHookTests(unittest.TestCase):
    def test_hook_rejects_private_value_with_bom_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scripts = root / 'scripts'
            (scripts / 'hooks').mkdir(parents=True)
            source = Path(__file__).resolve().parents[1] / 'scripts'
            shutil.copy2(source / 'check_staged.py', scripts / 'check_staged.py')
            shutil.copy2(source / 'hooks' / 'pre-commit', scripts / 'hooks' / 'pre-commit')
            (root / 'local').mkdir()
            state = {'preferred_sender':'owner@example.invalid','signature':'Example Signature',
                     'sent':[{'to':'private@example.invalid','result':{'id':'private-id','thread_id':'private-thread'}}]}
            (root / 'local' / 'GTM_Design_Partners_Etat.json').write_text(json.dumps(state), encoding='utf-8-sig')
            def git(*args):
                return subprocess.run(['git','-c','safe.directory='+root.as_posix(),*args],cwd=root,capture_output=True,text=True)
            self.assertEqual(git('init').returncode,0)
            self.assertEqual(git('config','core.hooksPath','scripts/hooks').returncode,0)
            (root / 'README.md').write_text('private@example.invalid',encoding='utf-8')
            self.assertEqual(git('add','README.md').returncode,0)
            rejected=git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','must reject')
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('private campaign value found',rejected.stderr)
            (root / 'README.md').write_text('Generic documentation.',encoding='utf-8')
            self.assertEqual(git('add','README.md').returncode,0)
            accepted=git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','allowed')
            self.assertEqual(accepted.returncode,0,accepted.stderr)


if __name__ == '__main__':
    unittest.main()
