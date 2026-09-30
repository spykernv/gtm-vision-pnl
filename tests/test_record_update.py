import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gtm import Store, atomic, read, Blocked
from test_runtime import ACCOUNT
class RecordUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.store=Store(self.tmp.name)
        atomic(self.store.path,{'preferred_sender':ACCOUNT,'signature':'Test Owner\n+00 000',
          'sent':[{'rank':1,'company':'Example','to':'prospect@example.invalid','result':{'id':'out1','thread_id':'t1'},
                   'actual_from':ACCOUNT,'conversation_state':'WAITING_REPLY','auto_reply_count':0}],
          'records':[{'Rang':1,'Entreprise':'Example','Statut':'Envoyé'},
                     {'Rang':2,'Entreprise':'Test Shop','Statut':'À qualifier','Contact public':None,'Email professionnel':None}],
          'local_runtime':{'revision':0,'mode':'live','events':{},'notifications':{},'gates':{'tested':True}}})
        self.item={'authorization':'User asked to enrich','evidence':{'source':'chat 2026-09-29'},'rank':2,'company':'test shop',
          'fields':{'Contact public':'Jane Founder (CEO)','Email professionnel':'jane@example.invalid'}}
    def test_updates_fields_and_audits_before_after(self):
        r=self.store.record_update(self.item); s=read(self.store.path)
        row=next(x for x in s['records'] if x['Rang']==2)
        self.assertEqual((row['Contact public'],row['Email professionnel'],row['Statut']),('Jane Founder (CEO)','jane@example.invalid','À qualifier'))
        audit=s['local_runtime']['record_updates'][0]
        self.assertEqual((audit['before']['Email professionnel'],audit['after']['Email professionnel']),(None,'jane@example.invalid'))
        self.assertEqual(r['updated'],['Contact public','Email professionnel'])
    def test_refuses_without_authorization_or_evidence(self):
        for k in ('authorization','evidence'):
            bad=dict(self.item); bad.pop(k)
            with self.assertRaises(Blocked): self.store.record_update(bad)
    def test_contacted_row_only_gains_its_decision_maker(self):
        dm={'Décideur':'John Boss — CEO','Email décideur':'john@example.invalid','Décideur : provenance':'Clay'}
        self.store.record_update(dict(self.item,rank=1,company='Example',fields=dm))
        row=next(x for x in read(self.store.path)['records'] if x['Rang']==1)
        self.assertEqual((row['Décideur'],row['Statut']),('John Boss — CEO','Envoyé'))
        phone={'Téléphone':'+33 1 00 00 00 00','Téléphone : provenance':'https://example.invalid/contact'}
        self.store.record_update(dict(self.item,rank=1,company='Example',fields=phone))
        row=next(x for x in read(self.store.path)['records'] if x['Rang']==1)
        self.assertEqual((row['Téléphone'],row['Statut']),('+33 1 00 00 00 00','Envoyé'))
        for fields in ({'Email professionnel':'other@example.invalid'},{'Contact public':'John'},
                       {'Email décideur':'prospect@example.invalid'}):
            with self.assertRaises(Blocked): self.store.record_update(dict(self.item,rank=1,company='Example',fields=fields))
    def test_historical_mailbox_rows_stay_untouched(self):
        s=read(self.store.path); s['sent'][0]['actual_from']='old@example.invalid'; atomic(self.store.path,s)
        with self.assertRaises(Blocked):
            self.store.record_update(dict(self.item,rank=1,company='Example',fields={'Décideur':'John Boss — CEO'}))
    def test_refuses_mismatched_locked_and_bad_email(self):
        bads=[dict(self.item,company='Other'),
              dict(self.item,fields={'Statut':'Envoyé'}),dict(self.item,fields={'Bogus':1}),dict(self.item,fields={}),
              dict(self.item,fields={'Email professionnel':'prospect@example.invalid'}),
              dict(self.item,fields={'Email professionnel':'a@example.invalid, b@example.invalid'})]
        for bad in bads:
            with self.assertRaises(Blocked): self.store.record_update(bad)
        self.assertNotIn('record_updates',read(self.store.path)['local_runtime'])
if __name__=='__main__':
    unittest.main(verbosity=2)
