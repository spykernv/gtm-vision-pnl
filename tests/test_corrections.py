import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest

import test_runtime as fixtures
from test_runtime import ACCOUNT, CONTACT, message
from gtm import Blocked, atomic, now, read


class CorrectionTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp
    claimed = fixtures.RuntimeTests.claimed
    receipt_data = fixtures.RuntimeTests.receipt_data

    def backup(self):
        p = self.store.local / 'backups' / 'test-backup.json'
        atomic(p, read(self.store.path))
        return p

    def test_restore_cannot_erase_uncertain_send(self):
        backup = self.backup()
        claim = self.claimed()
        self.store.arm(claim)
        before = self.store.path.read_bytes()
        with self.assertRaises(Blocked):
            self.store.restore(backup)
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(self.store.status()['uncertain_sends'], [claim['key']])

    def test_restore_cannot_erase_confirmed_send(self):
        backup = self.backup()
        claim = self.claimed()
        self.store.arm(claim)
        self.store.receipt(self.receipt_data(claim))
        with self.assertRaises(Blocked):
            self.store.restore(backup)
        self.assertEqual(read(self.store.path)['sent'][0]['auto_reply_count'], 1)

    def test_restore_cannot_reopen_refusal(self):
        backup = self.backup()
        self.store.ingest(dict(self.item, classification='refusal'))
        with self.assertRaises(Blocked):
            self.store.restore(backup)
        self.assertEqual(read(self.store.path)['sent'][0]['conversation_state'], 'STOPPED')

    def test_safe_restore_keeps_monotonic_revision(self):
        backup = self.backup()
        self.store.ingest(self.item)
        rev = self.store.status()['revision']
        self.store.restore(backup)
        self.assertGreater(self.store.status()['revision'], rev)
        self.assertEqual(self.store.status()['mode'], 'monitor')

    def test_labels_do_not_invalidate_reply(self):
        claim = self.claimed()
        refreshed = copy.deepcopy(self.thread)
        refreshed['messages'][-1]['label_ids'] = ['STARRED', 'IMPORTANT']
        refreshed['messages'][-1]['snippet'] = 'New summary'
        self.store.arm(dict(claim, thread=refreshed))
        self.assertEqual(self.store.status()['uncertain_sends'], [claim['key']])

    def test_changed_thread_reclassification_discards_draft(self):
        claim = self.claimed()
        changed = copy.deepcopy(self.thread)
        changed['messages'].append(message('in2', CONTACT))
        with self.assertRaises(Blocked):
            self.store.arm(dict(claim, thread=changed))
        e = read(self.store.path)['local_runtime']['events'][claim['key']]
        self.store.reclassify(dict(self.item, thread=changed, expected_fingerprint=e['thread_fingerprint']))
        updated = read(self.store.path)['local_runtime']['events'][claim['key']]
        self.assertNotIn('claim', updated)
        self.assertNotIn('body', updated)
        self.assertEqual(len(updated['reclassification_history']), 1)
        with self.assertRaises(Blocked):
            self.store.arm(dict(claim, thread=changed))
        new = self.store.prepare({'key':claim['key'], 'body':'Reviewed.\nTest Owner\n+00 000','subject':'Re: Pilote'})
        self.store.arm(dict(new, profile_email=ACCOUNT, thread=changed, checked_at=now()))

    def test_reclassification_respects_manual_takeover(self):
        claim = self.claimed()
        e = read(self.store.path)['local_runtime']['events'][claim['key']]
        thread = copy.deepcopy(self.thread)
        thread['messages'].append(message('manual', ACCOUNT, True))
        result = self.store.reclassify(dict(self.item, thread=thread, expected_fingerprint=e['thread_fingerprint']))
        self.assertEqual(result['state'], 'HANDOFF')
        with self.assertRaises(Blocked):
            self.store.prepare({'key':claim['key'], 'body':'Test Owner\n+00 000','subject':'Re: Pilote'})

    def test_reclassification_cannot_reopen_send_or_stale_event(self):
        claim = self.claimed()
        e = read(self.store.path)['local_runtime']['events'][claim['key']]
        with self.assertRaises(Blocked):
            self.store.reclassify(dict(self.item, expected_fingerprint='stale'))
        self.store.arm(claim)
        with self.assertRaises(Blocked):
            self.store.reclassify(dict(self.item, expected_fingerprint=e['thread_fingerprint']))

    def test_noop_recover_duplicates_and_block_do_not_create_backups(self):
        claim = self.claimed()
        before = self.store.path.read_bytes()
        count = len(list((self.store.local/'backups').glob('*.json')))
        self.store.recover()
        self.store.ingest(self.item)
        changed = copy.deepcopy(self.thread)
        changed['messages'].append(message('in2', CONTACT))
        with self.assertRaises(Blocked):
            self.store.arm(dict(claim, thread=changed))
        self.assertEqual(before, self.store.path.read_bytes())
        self.assertEqual(count, len(list((self.store.local/'backups').glob('*.json'))))

    def test_summary_migration_preserves_historical_metadata(self):
        s = read(self.store.path)
        s['automation'] = {'enabled':True, 'historical':True}
        s['unresolved_current'] = ['old blocker']
        atomic(self.store.path,s)
        self.store.sync()
        s=read(self.store.path)
        self.assertTrue(s['historical_metadata']['automation']['historical'])
        self.assertNotIn('automation',s)
        self.assertEqual(s['unresolved_current'],[])
        self.assertTrue(s['auto_reply_enabled'])
        self.store.mode('stop')
        self.assertFalse(read(self.store.path)['auto_reply_enabled'])

    def test_readonly_verifier_does_not_mutate_any_file(self):
        self.store.sync()
        delivery=self.store.local/'evidence'/'DELIVERY.md'
        delivery.parent.mkdir(exist_ok=True)
        delivery.write_text('Preserve report',encoding='utf-8')
        def manifest():
            return {str(p.relative_to(self.store.root)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in self.store.root.rglob('*') if p.is_file()}
        before=manifest()
        script=Path(__file__).resolve().parents[1]/'scripts'/'verify_installation.py'
        result=subprocess.run([sys.executable,'-B',str(script),'--root',str(self.store.root)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(before,manifest())


if __name__ == '__main__':
    unittest.main()
