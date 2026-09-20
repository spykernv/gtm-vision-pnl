import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from gtm import Store, Blocked, atomic, now, read, mutex
from datetime import datetime, timezone, timedelta

ACCOUNT = 'owner@example.invalid'
CONTACT = 'prospect@example.invalid'

def message(mid, sender, sent=False, body='Question simple', auto=False):
    h = [{'name':'From','value':sender},{'name':'To','value':CONTACT if sent else ACCOUNT},{'name':'Subject','value':'Re: Pilote'}]
    h.append({'name':'Message-ID','value':f'<{mid}@example.invalid>'})
    if mid == 'reply1':
        h.append({'name':'In-Reply-To','value':'<in1@example.invalid>'})
    if auto:
        h.append({'name':'Auto-Submitted','value':'auto-replied'})
    return {'id':mid,'thread_id':'t1','internal_date':str(int((datetime.now(timezone.utc)+timedelta(seconds=1)).timestamp()*1000)),'label_ids':['SENT'] if sent else ['INBOX'],
            'payload':{'mime_type':'text/plain','headers':h,'body':{'content':body}}}

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        state = {'preferred_sender':ACCOUNT,'signature':'Test Owner\n+00 000',
            'calendly':{'selected_event_url':'https://example.invalid/meeting','selected_event_uri':'et1','user_uri':'host1'},
            'sent':[{'actual_from':ACCOUNT,'to':CONTACT,'result':{'id':'out1','thread_id':'t1'},'conversation_state':'WAITING_REPLY','auto_reply_count':0}],
            'local_runtime':{'revision':0,'mode':'live','events':{},'notifications':{},'gates':{'tested':True}}}
        atomic(self.store.path,state)
        self.thread = {'id':'t1','complete':True,'messages':[message('out1',ACCOUNT,True),message('in1',CONTACT)]}
        self.item = {'account':ACCOUNT,'thread':self.thread,'inbound_id':'in1','classification':'simple_question','evidence':'Synthetic fixture'}

    def claimed(self):
        key = self.store.ingest(self.item)['key']
        claim = self.store.prepare({'key':key,'body':'Factuel.\nTest Owner\n+00 000','subject':'Re: Pilote'})
        return dict(claim,profile_email=ACCOUNT,thread=self.thread,checked_at=now())

    def receipt_data(self, claim):
        return {'key':claim['key'],'claim':claim['claim'],'account':ACCOUNT,
                'message':message('reply1',ACCOUNT,True,'Factuel.\nTest Owner\n+00 000')}

    def test_duplicate_inbound(self):
        first = self.store.ingest(self.item)
        second = self.store.ingest(self.item)
        self.assertTrue(second['duplicate'])
        self.assertEqual(first['key'], second['key'])
        self.assertEqual(len(read(self.store.path)['local_runtime']['events']),1)

    def test_refusal_stops(self):
        self.item['classification'] = 'refusal'
        result = self.store.ingest(self.item)
        self.assertEqual(result['state'],'STOPPED')
        with self.assertRaises(Blocked):
            self.store.prepare({'key':result['key'],'body':'Test Owner\n+00 000','subject':'Re: Pilote'})

    def test_manual_reply_after_claim(self):
        claim = self.claimed()
        claim['thread'] = copy.deepcopy(self.thread)
        claim['thread']['messages'].append(message('human',ACCOUNT,True))
        with self.assertRaises(Blocked):
            self.store.arm(claim)
        self.assertEqual(read(self.store.path)['sent'][0]['conversation_state'],'HANDOFF')

    def test_save_failure_after_send_and_restart(self):
        claim = self.claimed()
        self.store.arm(claim)
        with patch.object(self.store,'commit',side_effect=OSError('Disk write failed')):
            with self.assertRaises(OSError):
                self.store.receipt(self.receipt_data(claim))
        self.assertEqual(self.store.status()['uncertain_sends'],[claim['key']])
        restarted = Store(self.tmp.name)
        restarted.recover()
        self.assertEqual(restarted.status()['uncertain_sends'],[])
        self.assertEqual(read(restarted.path)['sent'][0]['auto_reply_count'],1)
        restarted.recover()
        self.assertEqual(read(restarted.path)['sent'][0]['auto_reply_count'],1)

    def test_crash_with_no_receipt_never_resends(self):
        claim = self.claimed()
        self.store.arm(claim)
        restarted = Store(self.tmp.name)
        restarted.recover()
        with self.assertRaises(Blocked):
            restarted.arm(claim)
        with self.assertRaises(Blocked):
            restarted.release(claim['key'])

    def test_receipt_wrong_account_rejected(self):
        claim = self.claimed()
        self.store.arm(claim)
        receipt = self.receipt_data(claim)
        receipt['account'] = 'wrong@example.invalid'
        with self.assertRaises(Blocked):
            self.store.receipt(receipt)

    def test_only_one_claim_per_thread(self):
        self.claimed()
        other = copy.deepcopy(self.item)
        other['inbound_id'] = 'in2'
        other['thread']['messages'].append(message('in2',CONTACT))
        key = self.store.ingest(other)['key']
        with self.assertRaises(Blocked):
            self.store.prepare({'key':key,'body':'Test Owner\n+00 000','subject':'Re: Pilote'})

    def test_concurrent_writer_blocked(self):
        with mutex(self.store.local / 'journal.lock'):
            with self.assertRaises(Blocked):
                self.store.ingest(self.item)

    def test_emergency_stop(self):
        claim = self.claimed()
        self.store.mode('stop')
        with self.assertRaises(Blocked):
            self.store.arm(claim)

    def test_automatic_no_reply(self):
        self.item['thread']['messages'][-1] = message('in1',CONTACT,auto=True)
        result = self.store.ingest(self.item)
        self.assertEqual(result['phase'],'SAVED')
        self.assertFalse(read(self.store.path)['local_runtime']['notifications'])

    def test_three_replies_handoff(self):
        with self.store.transaction() as state:
            state['sent'][0]['auto_reply_count'] = 3
        self.assertEqual(self.store.ingest(self.item)['state'],'HANDOFF')

    def test_incomplete_thread_blocked(self):
        self.item['thread']['complete'] = False
        with self.assertRaises(Blocked):
            self.store.ingest(self.item)

    def test_changed_thread_blocks(self):
        claim = self.claimed()
        claim['thread'] = copy.deepcopy(self.thread)
        claim['thread']['messages'].append(message('newer',CONTACT))
        with self.assertRaises(Blocked):
            self.store.arm(claim)

    def test_pagination_restart_and_no_early_watermark(self):
        page = {'scan_id':'scan-v2-1','query':'fixed query','started_at':now(),'page_token':None,'next_page_token':'p2','message_ids':['in1']}
        self.store.scan_page(page)
        self.assertIsNone(self.store.status()['last_completed_scan'])
        restarted = Store(self.tmp.name)
        page.update(page_token='p2',next_page_token=None,message_ids=['in1','in2'])
        result = restarted.scan_page(page)
        self.assertEqual(result['message_ids'],['in1','in2'])
        self.assertTrue(result['complete'])

    def test_booking_requires_actual_invitee(self):
        item={'account':ACCOUNT,'thread_id':'t1','event':{'uri':'booking1','status':'active','event_type':'et1','start_time':'2026-10-01T10:00:00Z','event_memberships':[{'user':'host1'}]},'invitee':{'status':'active','event':'booking1','email':'wrong@example.invalid','timezone':'Europe/Paris'}}
        with self.assertRaises(Blocked):
            self.store.booking(item)
        item['invitee']['email']=CONTACT
        self.store.booking(item)
        self.assertEqual(read(self.store.path)['sent'][0]['conversation_state'],'BOOKED')

    def test_save_failure_before_send_creates_no_claim(self):
        with patch.object(self.store,'commit',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.ingest(self.item)
        self.assertEqual(self.store.status()['events'],0)

    def test_backup_restore_enters_monitor(self):
        self.store.ingest(self.item)
        with self.store.transaction() as state:
            state['local_runtime']['gates']['scheduled_run_verified']=True
        backup=next((self.store.local/'backups').glob('*.json'))
        self.store.restore(backup)
        self.assertEqual(self.store.status()['mode'],'monitor')

    def test_detached_automatic_exact_reference(self):
        detached=message('detached',CONTACT,auto=True)
        detached['thread_id']='other-thread'
        detached['payload']['headers'].append({'name':'In-Reply-To','value':'<out1@example.invalid>'})
        self.item.update(inbound_id='detached',detached_message=detached)
        result=self.store.ingest(self.item)
        self.assertEqual(result['phase'],'SAVED')
        self.assertEqual(read(self.store.path)['local_runtime']['events'][result['key']]['classification'],'automatic')

    def test_detached_unlinked_rejected(self):
        detached=message('detached',CONTACT,auto=True)
        detached['thread_id']='other-thread'
        self.item.update(inbound_id='detached',detached_message=detached)
        with self.assertRaises(Blocked):
            self.store.ingest(self.item)

    def test_old_outbound_cannot_confirm_new_reply(self):
        claim=self.claimed()
        self.store.arm(claim)
        receipt=self.receipt_data(claim)
        receipt['message']['internal_date']='1000'
        with self.assertRaises(Blocked):
            self.store.receipt(receipt)

if __name__ == '__main__':
    unittest.main(verbosity=2)
