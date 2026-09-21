import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gtm import Store, atomic, read, now, Blocked
from test_runtime import ACCOUNT
class RecordAddTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.store=Store(self.tmp.name)
        atomic(self.store.path,{'preferred_sender':ACCOUNT,'signature':'Test Owner\n+00 000',
          'sent':[{'rank':1,'company':'Example','to':'prospect@example.invalid','result':{'id':'out1','thread_id':'t1'},
                   'actual_from':ACCOUNT,'conversation_state':'WAITING_REPLY','auto_reply_count':0}],
          'records':[{'Rang':1,'Entreprise':'Example','Statut':'Envoyé'}],
          'local_runtime':{'revision':0,'mode':'live','events':{},'notifications':{},'gates':{'tested':True}}})
        self.item={'authorization':'User asked for a test row','evidence':{'source':'chat 2026-09-21'},
          'record':{'Rang':2,'Entreprise':'Test Shop','Pays':'FR','Email professionnel':'test@example.invalid'}}
    def test_adds_row_with_defaults_and_audit(self):
        r=self.store.record_add(self.item); s=read(self.store.path)
        row=next(x for x in s['records'] if x['Rang']==2)
        self.assertEqual((r['records'],row['Statut'],row['Vague'],row['Sélection'],row['Shopify']),(2,'À qualifier',None,'Réserve',None))
        self.assertEqual(len(row),18)
        self.assertEqual(s['local_runtime']['record_additions'][0]['company'],'Test Shop')
    def test_refuses_without_authorization_or_evidence(self):
        for k in ('authorization','evidence'):
            bad=dict(self.item); bad.pop(k)
            with self.assertRaises(Blocked): self.store.record_add(bad)
        self.assertEqual(len(read(self.store.path)['records']),1)
    def test_refuses_duplicates_contacted_and_malformed(self):
        for rec in ({'Rang':1,'Entreprise':'Other'},{'Rang':3,'Entreprise':'example'},
                    {'Rang':3,'Entreprise':'New','Email professionnel':'prospect@example.invalid'},
                    {'Rang':'3','Entreprise':'New'},{'Rang':True,'Entreprise':'New'},{'Rang':3,'Entreprise':'New','Bogus':1}):
            with self.assertRaises(Blocked): self.store.record_add(dict(self.item,record=rec))
        self.assertEqual(len(read(self.store.path)['records']),1)
    def test_added_row_can_be_armed_but_not_twice(self):
        self.store.record_add(self.item)
        with self.assertRaises(Blocked): self.store.record_add(self.item)
        arm=self.store.outbound_arm({'profile_email':ACCOUNT,'authorization':'go','checked_at':now(),
          'duplicate_check':{'message_ids':[],'next_page_token':None},
          'campaign':{'rank':2,'company':'Test Shop','to':'test@example.invalid','name':'Team','wave':9,
          'subject':'Pilote','body':'Q.\nTest Owner\n+00 000','source':'test','proof':'test'}})
        self.assertEqual(arm['key'],'outbound:2')
        self.assertEqual(self.store.status()['uncertain_sends'],['outbound:2'])
if __name__=='__main__':
    unittest.main(verbosity=2)
