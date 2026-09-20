import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import test_runtime as fixtures
from gtm import Store, Blocked, atomic, next_scan_id, now, read
from backup_local import backup, inventory
from retention import checked_child, retained


class RetentionTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp
    claimed = fixtures.RuntimeTests.claimed

    def page(self, ids=None):
        rt = read(self.store.path)['local_runtime']
        return dict(scan_id=next_scan_id(rt), query='synthetic', started_at=now(),
                    page_token=None, next_page_token=None, message_ids=ids or ['out1'])

    def test_ninety_days_hourly_is_bounded_and_restorable(self):
        base = datetime(2027, 1, 1, tzinfo=timezone.utc)
        early_size = None
        with tempfile.TemporaryDirectory() as destination:
            for day in range(90):
                for hour in range(24):
                    stamp = base + timedelta(days=day, hours=hour)
                    with patch('gtm.now', return_value=stamp.isoformat()):
                        self.store.scan_page(dict(self.page(), started_at=stamp.isoformat()))
                class Clock(datetime):
                    @classmethod
                    def now(cls, tz=None):
                        return stamp
                with patch('backup_local.datetime', Clock):
                    result = backup(self.store.root, destination)
                self.assertNotIn('cleanup_error', result)
                self.assertLessEqual(len(list((self.store.local/'backups').glob('journal-*.json'))), 90)
                self.assertLessEqual(len(list(Path(destination).glob('gtm-*'))), 66)
                if day == 3:
                    early_size = self.store.path.stat().st_size
            self.assertLess(self.store.path.stat().st_size, early_size + 300)
            rt = read(self.store.path)['local_runtime']
            self.assertEqual(rt['scan_sequence'], 2160)
            self.assertEqual(len(rt['scan_history']), 24)
            old_id = dict(self.page(), scan_id='scan-v2-1')
            with self.assertRaises(Blocked): self.store.scan_page(old_id)
            # Restore a retained journal; latest cursor and replay sequence survive.
            snapshots = list((self.store.local/'backups').glob('journal-*.json'))
            candidate = max(snapshots, key=lambda p: read(p)['local_runtime']['revision'])
            self.store.restore(candidate)
            self.assertEqual(read(self.store.path)['local_runtime']['scan_sequence'], 2160)
            self.assertEqual(self.store.status()['mode'], 'monitor')
            # The external snapshot is also a complete isolated recovery source.
            with tempfile.TemporaryDirectory() as restored:
                shutil.copytree(Path(result['backup'])/'local', Path(restored)/'local')
                recovered = Store(restored)
                (recovered.local/'STOP').write_text('recovery test')
                self.assertEqual(recovered.recover(), {'recovered': []})
                self.assertTrue(recovered.status()['emergency_stop'])
                self.assertEqual(read(recovered.path)['local_runtime']['scan_sequence'], 2160)

    def test_pending_ids_survive_compaction_and_process_restart(self):
        self.store.scan_page(self.page(['pending-unclassified']))
        for _ in range(35): self.store.scan_page(self.page())
        rt = read(self.store.path)['local_runtime']
        self.assertIn('pending-unclassified', rt['scan']['message_ids'])
        self.assertEqual(len(rt['scan_history']), 24)
        restarted = Store(self.store.root)
        with self.assertRaises(Blocked):
            restarted.scan_page(dict(self.page(), scan_id='scan-v2-1'))

    def test_legacy_incomplete_scan_can_finish_before_new_protocol(self):
        state = read(self.store.path)
        state['local_runtime']['scan'] = dict(id='legacy',query='old',started_at=now(),
            next_page_token='cursor',message_ids=['in1'],pages=[None],complete=False)
        atomic(self.store.path,state)
        old = state['local_runtime']['scan']
        self.store.scan_page(dict(scan_id='legacy',query='old',started_at=old['started_at'],
            page_token='cursor',next_page_token=None,message_ids=[]))
        self.store.scan_page(self.page())
        self.assertEqual(read(self.store.path)['local_runtime']['scan_sequence'],1)

    def test_incident_archive_failure_preserves_journal(self):
        state=read(self.store.path)
        incident=dict(id='old',abandoned_at=now(),abandon_reason='expired',message_ids=['pending'])
        state['local_runtime']['scan_history']=[incident]+[dict(id=str(i)) for i in range(24)]
        state['local_runtime']['scan']=dict(id='legacy',message_ids=[],complete=True)
        atomic(self.store.path,state)
        before=self.store.path.read_bytes()
        with patch('gtm.atomic',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.compact_scans()
        self.assertEqual(before,self.store.path.read_bytes())
        self.store.compact_scans()
        archived=list((self.store.local/'scan-incidents').glob('*.json'))
        self.assertEqual(read(archived[0]),incident)
        self.assertIn('pending',read(self.store.path)['local_runtime']['scan']['message_ids'])

    def test_backups_excluded_but_receipts_and_evidence_retained(self):
        self.store.sync()
        atomic(self.store.local/'receipts'/'proof.json',{'synthetic':True})
        atomic(self.store.local/'evidence'/'proof.json',{'synthetic':True})
        with tempfile.TemporaryDirectory() as dest:
            result=backup(self.store.root,dest)
            files=read(Path(result['backup'])/'manifest.json')['sha256']
            self.assertFalse(any(p.startswith('backups/') for p in files))
            self.assertIn('receipts/proof.json',files)
            self.assertIn('evidence/proof.json',files)

    def test_corrupt_new_copy_does_not_prune_any_existing_copy(self):
        for _ in range(52): self.store.scan_page(self.page())
        before=inventory(self.store.local)
        with tempfile.TemporaryDirectory() as dest:
            copy2=shutil.copy2
            def corrupt(src,dst):
                copy2(src,dst);Path(dst).write_bytes(b'corrupt')
            with patch('backup_local.shutil.copy2',side_effect=corrupt):
                with self.assertRaises(Blocked): backup(self.store.root,dest)
            self.assertEqual(before,inventory(self.store.local))

    def test_uncertain_send_pins_copies_and_survives_external_restore(self):
        for _ in range(52): self.store.scan_page(self.page())
        claim=self.claimed();self.store.arm(claim)
        count=len(list((self.store.local/'backups').glob('*.json')))
        with tempfile.TemporaryDirectory() as dest:
            result=backup(self.store.root,dest)
            self.assertEqual(result['retention']['skipped'],'unresolved_send_ownership')
            self.assertEqual(len(list((self.store.local/'backups').glob('*.json'))),count)
            with tempfile.TemporaryDirectory() as recovered:
                shutil.copytree(Path(result['backup'])/'local',Path(recovered)/'local')
                store=Store(recovered);store.recover()
                self.assertEqual(store.status()['uncertain_sends'],[claim['key']])
                with self.assertRaises(Blocked): store.release(claim['key'])

    def test_snapshot_cleanup_preserves_unique_evidence_and_unknown_folders(self):
        with tempfile.TemporaryDirectory() as dest, patch('retention.REMOTE_RECENT',2):
            proof=self.store.local/'evidence'/'unique.json';atomic(proof,{'old':True})
            first=backup(self.store.root,dest)
            atomic(proof,{'new':True})
            backup(self.store.root,dest)
            foreign=Path(dest)/'untouched.partial';foreign.mkdir()
            (foreign/'value').write_text('keep')
            result=backup(self.store.root,dest)
            self.assertTrue(Path(first['backup']).exists())
            self.assertEqual(result['retention']['snapshots_pinned'],1)
            self.assertTrue((foreign/'value').exists())

    def test_corrupt_old_snapshot_blocks_cleanup_but_new_copy_succeeds(self):
        with tempfile.TemporaryDirectory() as dest, patch('retention.REMOTE_RECENT',2):
            first=backup(self.store.root,dest)
            backup(self.store.root,dest)
            (Path(first['backup'])/'local'/'GTM_Design_Partners_Etat.json').write_text('corrupt')
            result=backup(self.store.root,dest)
            self.assertTrue(result['verified_local_copy'])
            self.assertIn('cleanup_error',result)
            self.assertTrue(Path(first['backup']).exists())

    def test_local_cleanup_protects_saved_events_and_business_stops(self):
        self.store.ingest(dict(self.item,classification='refusal'))
        before=read(self.store.path)
        for _ in range(52): self.store.scan_page(self.page())
        with tempfile.TemporaryDirectory() as dest:
            result=backup(self.store.root,dest)
            self.assertGreater(result['retention']['local_backups_removed'],0)
            copied=read(Path(result['backup'])/'local'/'GTM_Design_Partners_Etat.json')
            self.assertEqual(copied['sent'],before['sent'])
            self.assertEqual(copied['local_runtime']['events'],before['local_runtime']['events'])

    def test_path_escape_and_linked_root_refused(self):
        with self.assertRaises(Blocked): checked_child(self.store.root,self.store.local)
        with patch.object(Path,'is_junction',return_value=True):
            with self.assertRaises(Blocked): inventory(self.store.local)

    def test_policy_retains_daily_and_monthly_recovery_points(self):
        start=datetime(2026,1,1,tzinfo=timezone.utc)
        rows=[(str(i),start+timedelta(hours=i)) for i in range(24*730)]
        keep=retained(rows,24)
        self.assertLessEqual(len(keep),66)
        self.assertTrue(set(str(i) for i in range(len(rows)-24,len(rows)))<=keep)
        months={(t.year,t.month) for key,t in rows if key in keep}
        self.assertGreaterEqual(len(months),12)


if __name__=='__main__': unittest.main()
