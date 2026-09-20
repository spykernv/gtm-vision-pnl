import copy
import unittest
from unittest.mock import patch

import test_runtime as fixtures
from test_runtime import ACCOUNT, CONTACT
from gtm import Store, Blocked, atomic, now, read


class RecoveryReviewTests(unittest.TestCase):
    setUp = fixtures.RuntimeTests.setUp
    claimed = fixtures.RuntimeTests.claimed

    def page(self):
        return dict(scan_id='s1', query='synthetic', started_at=now(), page_token=None,
                    next_page_token='expired', message_ids=['in1'])

    def booking(self, uri='booking1'):
        return dict(account=ACCOUNT, thread_id='t1',
                    event=dict(uri=uri, status='active', event_type='et1',
                               start_time='2026-10-01T10:00:00Z', event_memberships=[{'user':'host1'}]),
                    invitee=dict(status='active', event=uri, email=CONTACT, timezone='Europe/Paris'))

    def restart(self, page, new_id='s2'):
        return dict(scan_id=page['scan_id'], expected_page_token=page['next_page_token'],
                    new_scan_id=new_id, started_at=now(), reason='cursor_expired',
                    evidence='Synthetic Gmail invalid page token response')

    def test_expired_cursor_restarts_without_false_completion(self):
        page=self.page(); self.store.scan_page(page)
        restart=self.restart(page)
        result=self.store.scan_restart(restart)
        self.assertFalse(result['complete'])
        self.assertEqual(result['message_ids'], ['in1'])
        self.assertIsNone(self.store.status()['last_completed_scan'])
        rt=read(self.store.path)['local_runtime']
        self.assertFalse(rt['scan_history'][0]['complete'])
        self.assertEqual(rt['scan_history'][0]['abandon_reason'], 'cursor_expired')
        restarted=Store(self.store.root)
        first=dict(page,scan_id='s2',started_at=restart['started_at'],next_page_token='next',message_ids=['in2'])
        restarted.scan_page(first)
        self.assertIsNone(restarted.status()['last_completed_scan'])
        result=restarted.scan_page(dict(first,page_token='next',next_page_token=None,message_ids=[]))
        self.assertTrue(result['complete'])
        self.assertEqual(result['message_ids'],['in1','in2'])
        self.assertEqual(restarted.status()['last_completed_scan'],restart['started_at'])

    def test_restart_rejects_stale_cursor_missing_evidence_and_reused_ids(self):
        page=self.page();self.store.scan_page(page)
        valid=self.restart(page)
        for edit in ({'expected_page_token':'stale'},{'evidence':''},{'new_scan_id':'s1'}):
            before=self.store.path.read_bytes()
            with self.assertRaises(Blocked): self.store.scan_restart(dict(valid,**edit))
            self.assertEqual(before,self.store.path.read_bytes())
        self.store.scan_restart(valid)
        with self.assertRaises(Blocked): self.store.scan_restart(valid)
        with self.assertRaises(Blocked):
            self.store.scan_restart(dict(valid,scan_id='s2',expected_page_token=None,new_scan_id='s1'))

    def test_restart_save_failure_keeps_original_scan(self):
        page=self.page();self.store.scan_page(page)
        before=self.store.path.read_bytes()
        with patch.object(self.store,'commit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.scan_restart(self.restart(page))
        self.assertEqual(before,self.store.path.read_bytes())

    def test_old_page_and_changed_start_cannot_complete_restarted_scan(self):
        page=self.page();self.store.scan_page(page)
        restart=self.restart(page);self.store.scan_restart(restart)
        before=self.store.path.read_bytes()
        with self.assertRaises(Blocked):
            self.store.scan_page(dict(page,page_token='expired',next_page_token=None))
        with self.assertRaises(Blocked):
            self.store.scan_page(dict(page,scan_id='s2',started_at='2000-01-01T00:00:00Z',next_page_token=None))
        self.assertEqual(before,self.store.path.read_bytes())

    def test_second_booking_without_cancellation_cannot_overwrite_first(self):
        self.store.booking(self.booking())
        before=self.store.path.read_bytes()
        with self.assertRaises(Blocked): self.store.booking(self.booking('booking2'))
        self.assertEqual(before,self.store.path.read_bytes())

    def test_rebooking_preserves_prior_evidence_and_deduplicates(self):
        first=self.booking();self.store.booking(first)
        second=self.booking('booking2')
        second['previous_booking']={'event':dict(first['event'],status='canceled'),
                                    'invitee':dict(first['invitee'],status='canceled')}
        self.store.booking(second)
        state=read(self.store.path)
        c=state['sent'][0]
        self.assertEqual(c['calendly_event_uri'],'booking2')
        self.assertEqual(c['booking_history'][0]['booking_evidence'],first)
        self.assertEqual(c['booking_history'][0]['cancellation_evidence'],second['previous_booking'])
        self.assertEqual(len(state['local_runtime']['notifications']),2)
        before=self.store.path.read_bytes()
        self.store.booking(second)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_rebooking_rejects_wrong_cancellation_evidence(self):
        first=self.booking();self.store.booking(first)
        previous={'event':dict(first['event'],status='canceled'),
                  'invitee':dict(first['invitee'],status='canceled')}
        for part,field,value in [('event','uri','other'),('event','status','active'),
                                 ('event','event_type','other'),('invitee','email','other@example.invalid'),
                                 ('invitee','event','other'),('invitee','status','active')]:
            second=self.booking('booking2');second['previous_booking']=copy.deepcopy(previous)
            second['previous_booking'][part][field]=value
            before=self.store.path.read_bytes()
            with self.assertRaises(Blocked): self.store.booking(second)
            self.assertEqual(before,self.store.path.read_bytes())

    def test_same_booking_changed_evidence_is_archived(self):
        first=self.booking();self.store.booking(first)
        changed=copy.deepcopy(first);changed['event']['start_time']='2026-10-02T10:00:00Z'
        self.store.booking(changed)
        state=read(self.store.path)
        self.assertEqual(state['sent'][0]['booking_history'][0]['booking_evidence'],first)
        self.assertEqual(len(state['local_runtime']['notifications']),2)

    def test_restore_cannot_forget_saved_automatic_or_not_now(self):
        backup=self.store.local/'backups'/'before.json';atomic(backup,read(self.store.path))
        for kind in ('automatic','not_now'):
            self.store.ingest(dict(self.item,classification=kind))
            before=self.store.path.read_bytes()
            with self.assertRaises(Blocked): self.store.restore(backup)
            self.assertEqual(before,self.store.path.read_bytes())
            self.assertTrue(self.store.ingest(self.item)['duplicate'])
            # Isolated fixture reset between classifications.
            atomic(self.store.path,read(backup))

    def test_restore_cannot_rollback_booking_with_same_booked_state(self):
        first=self.booking();self.store.booking(first)
        backup=self.store.local/'backups'/'before.json';atomic(backup,read(self.store.path))
        changed=copy.deepcopy(first);changed['event']['start_time']='2026-10-02T10:00:00Z'
        self.store.booking(changed)
        before=self.store.path.read_bytes()
        with self.assertRaises(Blocked): self.store.restore(backup)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_old_fingerprint_requires_explicit_reclassification(self):
        claim=self.claimed()
        with self.store.transaction() as state:
            state['local_runtime']['events'][claim['key']].pop('fingerprint_version')
        with self.assertRaisesRegex(Blocked,'fingerprint version'):
            self.store.arm(claim)
        event=read(self.store.path)['local_runtime']['events'][claim['key']]
        self.store.reclassify(dict(self.item,expected_fingerprint=event['thread_fingerprint']))
        new=self.store.prepare({'key':claim['key'],'body':'Reviewed.\nTest Owner\n+00 000','subject':'Re: Pilote'})
        self.store.arm(dict(new,profile_email=ACCOUNT,thread=self.thread,checked_at=now()))

    def test_scan_scope_uses_earliest_eligible_send(self):
        with self.store.transaction() as state:
            state['sent'][0]['sent_date']='2026-09-19'
            other=copy.deepcopy(state['sent'][0]);other.update(actual_from=None,sent_date='2020-01-01')
            other['result']={'id':'old','thread_id':'old'};state['sent'].append(other)
        result=self.store.scan_scope()
        self.assertEqual(result['after_date'],'2026/09/18')
        self.assertEqual(result['thread_ids'],['t1'])
        self.assertNotIn('2020',result['query'])
        with self.store.transaction() as state: state['sent'][0]['conversation_state']='STOPPED'
        self.assertIsNone(self.store.scan_scope()['query'])

    def test_scan_scope_missing_date_blocks_instead_of_guessing(self):
        with self.assertRaises(Blocked): self.store.scan_scope()

    def test_restore_saved_snapshot_keeps_events_and_latest_scan(self):
        self.store.ingest(dict(self.item,classification='not_now',evidence='Later, not now'))
        backup=self.store.local/'backups'/'saved.json';atomic(backup,read(self.store.path))
        page=self.page();self.store.scan_page(page)
        restart=self.restart(page);self.store.scan_restart(restart)
        before=read(self.store.path)['local_runtime']
        self.store.restore(backup)
        after=read(self.store.path)['local_runtime']
        for field in ('events','scan','scan_history','last_completed_scan'):
            self.assertEqual(after.get(field),before.get(field))

    def test_restart_completed_scan_rejected(self):
        page=dict(self.page(),next_page_token=None)
        self.store.scan_page(page)
        before=self.store.path.read_bytes()
        with self.assertRaises(Blocked): self.store.scan_restart(self.restart(page))
        with self.assertRaises(Blocked): self.store.scan_page(page)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_legacy_saved_events_are_not_migrated_or_reopened(self):
        key=self.store.ingest(dict(self.item,classification='automatic'))['key']
        with self.store.transaction() as state:
            state['local_runtime']['events'][key].pop('fingerprint_version')
        before=self.store.path.read_bytes()
        self.store.recover()
        self.assertTrue(self.store.ingest(self.item)['duplicate'])
        self.assertEqual(before,self.store.path.read_bytes())

    def test_rebooking_preserves_business_stop_and_survives_restart(self):
        self.store.ingest(dict(self.item,classification='refusal'))
        first=self.booking();self.store.booking(first)
        second=self.booking('booking2')
        second['previous_booking']={'event':dict(first['event'],status='canceled'),
                                    'invitee':dict(first['invitee'],status='canceled')}
        restarted=Store(self.store.root);restarted.booking(second)
        self.assertEqual(read(self.store.path)['sent'][0]['conversation_state'],'STOPPED')
        before=self.store.path.read_bytes()
        restarted.booking(second)
        self.assertEqual(before,self.store.path.read_bytes())

    def test_rebooking_save_failure_keeps_first_booking(self):
        first=self.booking();self.store.booking(first)
        second=self.booking('booking2')
        second['previous_booking']={'event':dict(first['event'],status='canceled'),
                                    'invitee':dict(first['invitee'],status='canceled')}
        before=self.store.path.read_bytes()
        with patch.object(self.store,'commit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): self.store.booking(second)
        self.assertEqual(before,self.store.path.read_bytes())


if __name__=='__main__': unittest.main()
