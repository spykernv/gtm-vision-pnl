import json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from research import (draft_additions, draft_updates, fr_summary, is_generic, kbo_people, read_page, simulate,
                      summary_line, targets_of, variants, verdict)
from gtm import atomic
from test_runtime import ACCOUNT


def journal():
    return {'preferred_sender':ACCOUNT,'signature':'Test Owner\n+00 000',
            'sent':[{'rank':1,'company':'Written','to':'hello@written.example.invalid','result':{'id':'o1','thread_id':'t1'},
                     'actual_from':ACCOUNT,'conversation_state':'WAITING_REPLY','auto_reply_count':0},
                    {'rank':2,'company':'Old','to':'old@old.example.invalid','result':{'id':'o2','thread_id':'t2'},
                     'actual_from':'previous@example.invalid','conversation_state':'WAITING_REPLY','auto_reply_count':0}],
            'records':[{'Rang':1,'Entreprise':'Written','Statut':'Envoyé','Email professionnel':'hello@written.example.invalid',
                        'Site / preuve Shopify':'https://written.example.invalid'},
                       {'Rang':2,'Entreprise':'Old','Statut':'Envoyé','Site / preuve Shopify':'https://old.example.invalid'},
                       {'Rang':3,'Entreprise':'Fresh','Statut':'À qualifier','Email professionnel':'contact@fresh.example.invalid',
                        'Site / preuve Shopify':'https://www.fresh.example.invalid','À vérifier':'Taille inconnue'},
                       {'Rang':4,'Entreprise':'Named','Statut':'À qualifier','Email professionnel':'jane@named.example.invalid',
                        'Site / preuve Shopify':'https://named.example.invalid'},
                       {'Rang':5,'Entreprise':'Gone','Statut':'À qualifier','À vérifier':'À écarter : société cessée',
                        'Site / preuve Shopify':'https://gone.example.invalid'}],
            'local_runtime':{'revision':0,'mode':'live','events':{},'notifications':{},'gates':{'tested':True}}}


class ResearchTests(unittest.TestCase):
    def test_variants_cover_usual_formats_and_umlauts(self):
        v=variants('Jean-Paul De Test')
        for local in ('jean-paul','jean-paul.detest','jp.detest','jpdetest','jeanpaul','jean-paul.de-test'):
            self.assertIn(local,v)
        self.assertEqual(v[0],'jean-paul')
        self.assertIn('anna.hoefner',variants('Anna Höfner'))
        self.assertIn('anna.hofner',variants('Anna Höfner'))

    def test_generic_boxes_are_fallbacks_only(self):
        for a in ('hello@shop.example.invalid','sav@shop.example.invalid','service.client@shop.example.invalid'):
            self.assertTrue(is_generic(a))
        for a in ('jane@shop.example.invalid','j.doe@shop.example.invalid'):
            self.assertFalse(is_generic(a))

    def test_a_server_that_accepts_everything_proves_nothing(self):
        open_={'catch_all':False,'results':{'a@x.invalid':[250,''],'b@x.invalid':[550,''],'c@x.invalid':[450,'']}}
        self.assertEqual([verdict(open_,a) for a in ('a@x.invalid','b@x.invalid','c@x.invalid','d@x.invalid')],
                         ['valide','refusé','inconnu','inconnu'])
        self.assertEqual(verdict({'catch_all':True,'results':{'a@x.invalid':[250,'']}},'a@x.invalid'),'accepte-tout')

    def test_page_reading_keeps_emails_people_and_registry_ids(self):
        out={'emails':{},'people':[],'ids':{}}
        read_page('<p>Directrice de la publication : Jane Doe. RCS Paris 123 456 789.</p>'
                  '<a href="mailto:jane@shop.example.invalid">x</a> TVA BE 0123.456.789',
                  'https://shop.example.invalid/legal',out)
        self.assertIn('jane@shop.example.invalid',out['emails'])
        self.assertEqual(out['ids']['siren'],{'123456789'})
        self.assertEqual(out['ids']['bce'],{'0123456789'})
        self.assertTrue(out['people'])

    def test_registry_parsers_keep_people_and_roles(self):
        fr=fr_summary({'nom_complet':'SHOP SAS','siren':'123456789','tranche_effectif_salarie':'11',
                       'dirigeants':[{'type_dirigeant':'personne physique','prenoms':'JANE MARIE','nom':'DOE','qualite':'Président de SAS'}],
                       'finances':{'2024':{'ca':1000}}})
        self.assertEqual((fr['headcount'],fr['people'][0]['name'],fr['revenue']),('10-19','Jane Doe',{'2024':{'ca':1000}}))
        be=kbo_people('<h2>Fonctions</h2><tr><td>Gérant</td><td>Doe , Jane</td><td>Depuis 2020</td></tr><h2>Qualités</h2>')
        self.assertEqual(be,[{'name':'Jane Doe','role':'Gérant'}])


    def test_targets_skip_named_historical_and_set_aside_rows(self):
        t=targets_of(journal())
        self.assertEqual([(x['rank'],x['contacted'],x['domain']) for x in t],
                         [(1,True,'written.example.invalid'),(3,False,'fresh.example.invalid')])

    def test_summary_line_is_one_compact_line(self):
        line=summary_line({'rank':3,'company':'Fresh','domain':'fresh.example.invalid','pages_read':4,
                           'emails':{'contact@fresh.example.invalid':'u'},'named_emails':{}},
                          {'fr':{'legal_name':'FRESH SAS','siren':'123456789','created':'2020-01-01','headcount':'6-9',
                                 'headcount_year':'2023','active':'A','people':[{'name':'Jane Doe','role':'Président de SAS','via':'FRESH SAS'}],
                                 'revenue':{'2024':{'ca':2500000}}}})
        self.assertNotIn('\n',line)
        for part in ('Jane Doe (Président de SAS)','effectif 6-9 (2023)','CA 2024 2.5 M€','contact@fresh.example.invalid'):
            self.assertIn(part,line)

    def test_drafts_respect_contacted_rows_and_replay_on_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            j=journal(); root=Path(tmp)
            (root/'local').mkdir(); atomic(root/'local'/'GTM_Design_Partners_Etat.json',j)
            verify=root/'verify.json'
            verify.write_text(json.dumps({'written.example.invalid':{'verdicts':{'boss@written.example.invalid':'valide'}}}),encoding='utf-8')
            names=draft_updates([
                {'rank':1,'person':'Boss Person — CEO','email':'boss@written.example.invalid','proof':'smtp','source':'registre'},
                {'rank':3,'person':'Jane Fresh — présidente','email':'contact@fresh.example.invalid','proof':'fallback',
                 'source':'registre','checks':'Registre : 6-9 salariés'}],j,'test',root/'drafts',[verify],day='30/09/2026')
            dm=json.loads((root/'drafts'/'dm-001.json').read_text(encoding='utf-8'))
            self.assertEqual(sorted(dm['fields']),['Décideur','Décideur : provenance','Email décideur'])
            nc=json.loads((root/'drafts'/'nc-003.json').read_text(encoding='utf-8'))
            self.assertEqual(nc['fields']['À vérifier'],'Registre : 6-9 salariés ; Taille inconnue')
            with self.assertRaises(ValueError):
                draft_updates([{'rank':1,'person':'X','email':'x@written.example.invalid','proof':'smtp','source':'s'}],
                              j,'test',root/'drafts2',[verify])
            draft_additions([{'company':'Brand New','country':'BE','site':'https://brand.example.invalid','shop':'brand.myshopify.com',
                              'provenance':'Repli boutique','angle':'Retours','checks':'Taille inconnue'}],j,'test',root/'drafts')
            self.assertTrue((root/'drafts'/'add-006.json').exists())
            with self.assertRaises(ValueError):
                draft_additions([{'company':'fresh','country':'FR','site':'s','shop':'s','provenance':'p'}],j,'test',root/'drafts3')
            result=simulate(root/'drafts',root/'local'/'GTM_Design_Partners_Etat.json')
            self.assertEqual(result,{'add-006.json':'ok','dm-001.json':'ok','nc-003.json':'ok'})
            self.assertNotIn('record_updates',json.loads((root/'local'/'GTM_Design_Partners_Etat.json').read_text(encoding='utf-8'))['local_runtime'])


if __name__=='__main__':
    unittest.main(verbosity=2)
