import copy, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gtm import Store, atomic, read, now, Blocked
from test_runtime import message, ACCOUNT
class OutboundTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.store=Store(self.tmp.name)
        atomic(self.store.path,{'preferred_sender':ACCOUNT,'signature':'Test Owner\n+00 000','sent':[],
          'records':[{'Rang':1,'Entreprise':'Example','Statut':'À qualifier'}],
          'local_runtime':{'revision':0,'mode':'live','events':{},'notifications':{},'gates':{'tested':True}}})
        self.item={'profile_email':ACCOUNT,'authorization':'User requested one email','checked_at':now(),
          'duplicate_check':{'message_ids':[],'next_page_token':None},
          'campaign':{'rank':1,'company':'Example','to':'prospect@example.invalid','name':'Team','wave':1,
          'subject':'Pilote','body':'Question.\nTest Owner\n+00 000','source':'https://example.invalid/contact','proof':'https://example.invalid/'}}
    def arm_receipt(self):
        arm=self.store.outbound_arm(self.item)
        m=message('new1',ACCOUNT,True,self.item['campaign']['body'])
        m['payload']['headers']=[h for h in m['payload']['headers'] if h['name']!='Subject']+[{'name':'Subject','value':'Pilote'}]
        return dict(key=arm['key'],claim=arm['claim'],account=ACCOUNT,message=m)
    def test_success_and_idempotent_recovery(self):
        receipt=self.arm_receipt(); self.store.outbound_receipt(receipt)
        before=self.store.path.read_bytes(); self.store.recover()
        self.assertEqual(before,self.store.path.read_bytes())
        s=read(self.store.path); self.assertEqual(len(s['sent']),1)
        self.assertEqual(s['sent'][0]['auto_reply_count'],0)
        self.assertEqual(self.store.scan_scope()['thread_ids'],['t1'])
        with self.assertRaises(Blocked): self.store.outbound_arm(self.item)
    def test_uncertain_cannot_retry(self):
        self.store.outbound_arm(self.item)
        self.assertEqual(self.store.status()['uncertain_sends'],['outbound:1'])
        self.store.recover()
        with self.assertRaises(Blocked): self.store.outbound_arm(self.item)
    def test_wrong_proofs_do_not_mutate(self):
        receipt=self.arm_receipt()
        for field,value in [('account','wrong@example.invalid'),('claim','wrong')]:
            bad=copy.deepcopy(receipt);bad[field]=value
            with self.assertRaises(Blocked):self.store.outbound_receipt(bad)
        for name,value in [('To','wrong@example.invalid'),('Cc','other@example.invalid'),('Subject','Wrong'),('In-Reply-To','<old@example.invalid>')]:
            bad=copy.deepcopy(receipt);bad['message']['payload']['headers']=[h for h in bad['message']['payload']['headers'] if h['name']!=name]+[{'name':name,'value':value}]
            with self.assertRaises(Blocked):self.store.outbound_receipt(bad)
        self.assertEqual(len(read(self.store.path)['sent']),0)
    def test_crash_receipt_recovers(self):
        receipt=self.arm_receipt()
        with patch.object(self.store,'commit',side_effect=OSError('disk')):
            with self.assertRaises(OSError):self.store.outbound_receipt(receipt)
        self.assertEqual(self.store.status()['uncertain_sends'],['outbound:1'])
        self.store.recover(); self.assertEqual(len(read(self.store.path)['sent']),1)
    def test_restore_cannot_erase_intent(self):
        self.store.outbound_arm(self.item)
        old=next((self.store.local/'backups').glob('*.json'))
        before=self.store.path.read_bytes()
        with self.assertRaises(Blocked):self.store.restore(old)
        self.assertEqual(before,self.store.path.read_bytes())
    def recontact_item(self, **confirmation):
        item=copy.deepcopy(self.item); item['checked_at']=now()
        item['campaign']['to']='founder@example.invalid'
        item['duplicate_check']={'message_ids':['new1'],'next_page_token':None}
        if confirmation: item['recontact']=confirmation
        return item
    def recontact_receipt(self, arm):
        m=message('new2',ACCOUNT,True,self.item['campaign']['body']); m['thread_id']='t2'
        m['payload']['headers']=[h for h in m['payload']['headers'] if h['name'] not in ('Subject','To')]+[
            {'name':'Subject','value':'Pilote'},{'name':'To','value':'founder@example.invalid'}]
        return dict(key=arm['key'],claim=arm['claim'],account=ACCOUNT,message=m)
    def test_recontact_is_a_confirmed_rule_used_once(self):
        self.store.outbound_receipt(self.arm_receipt())
        with self.assertRaises(Blocked): self.store.outbound_arm(self.recontact_item())
        ok={'confirmed_by':'Jonathan','authorization':'« contourne le blocage pour ces mails »'}
        arm=self.store.outbound_arm(self.recontact_item(**ok))
        self.assertEqual(arm['key'],'recontact:1')
        self.store.outbound_receipt(self.recontact_receipt(arm))
        s=read(self.store.path)
        self.assertEqual([x['to'] for x in s['sent']],['prospect@example.invalid','founder@example.invalid'])
        self.assertEqual((s['sent'][1]['recontact']['previous_sends'],s['records'][0]['Email professionnel']),(['new1'],'founder@example.invalid'))
        with self.assertRaises(Blocked): self.store.outbound_arm(self.recontact_item(**ok))
    def test_recontact_keeps_stops_and_unread_mail(self):
        self.store.outbound_receipt(self.arm_receipt())
        ok={'confirmed_by':'Jonathan','authorization':'« contourne le blocage »'}
        unread=self.recontact_item(**ok); unread['duplicate_check']['message_ids']=['new1','reply9']
        with self.assertRaises(Blocked): self.store.outbound_arm(unread)
        unread['recontact']=dict(ok,reviewed_message_ids=['reply9']); unread['checked_at']=now()
        self.assertEqual(self.store.outbound_arm(unread)['key'],'recontact:1')
        s=read(self.store.path); s['local_runtime']['outbound_intents'].pop('recontact:1')
        s['sent'][0]['conversation_state']='STOPPED'; atomic(self.store.path,s)
        with self.assertRaises(Blocked): self.store.outbound_arm(self.recontact_item(**ok))
    def test_preflight_guards(self):
        for key,value in [('profile_email','wrong@example.invalid'),('authorization',''),('checked_at','2020-01-01T00:00:00+00:00'),('duplicate_check',{'message_ids':['old'],'next_page_token':None})]:
            bad=copy.deepcopy(self.item);bad[key]=value
            with self.assertRaises(Blocked):self.store.outbound_arm(bad)
        for field in ('subject','body'):
            bad=copy.deepcopy(self.item);bad['campaign'][field]='Boutique — '+bad['campaign'][field]
            with self.assertRaises(Blocked):self.store.outbound_arm(bad)
        (self.store.local/'STOP').touch()
        with self.assertRaises(Blocked):self.store.outbound_arm(self.item)
if __name__=='__main__':unittest.main()

