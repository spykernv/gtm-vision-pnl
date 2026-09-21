import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gtm import Store, Blocked, atomic, now, read
from test_runtime import ACCOUNT, CONTACT, message

SENT_AT = 1_789_820_000_000  # l'envoi initial ; chaque message suivant est postérieur.


def at(offset, *args, **kwargs):
    """Un message du fil, horodaté explicitement par rapport à l'envoi initial."""
    built = message(*args, **kwargs)
    built['internal_date'] = str(SENT_AT + offset)
    return built


class ManualReplyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        atomic(self.store.path, {'preferred_sender': ACCOUNT, 'signature': 'Test Owner\n+00 000',
            'calendly': {'selected_event_url': 'u', 'selected_event_uri': 'et1', 'user_uri': 'h1'},
            'sent': [{'actual_from': ACCOUNT, 'to': CONTACT, 'result': {'id': 'out1', 'thread_id': 't1'},
                      'sent_date': '2026-09-19', 'conversation_state': 'WAITING_REPLY', 'auto_reply_count': 0}],
            'records': [], 'local_runtime': {'revision': 0, 'mode': 'live', 'events': {},
                                             'notifications': {}, 'gates': {'tested': True}}})
        self.hand = at(7_200_000, 'byhand', ACCOUNT, True, 'Bonjour Éric, voici le lien.\nTest Owner\n+00 000')
        self.thread = {'id': 't1', 'complete': True,
                       'messages': [at(0, 'out1', ACCOUNT, True), at(3_600_000, 'in1', CONTACT), self.hand]}
        self.item = {'account': ACCOUNT, 'thread': self.thread, 'message_id': 'byhand',
                     'note': 'Réponse envoyée à la main', 'evidence': {'read': 'gmail get_thread'}}

    def test_records_proof_and_hands_the_thread_over(self):
        result = self.store.manual_reply(self.item)
        state = read(self.store.path)
        campaign = state['sent'][0]
        self.assertEqual((result['state'], result['manual_replies']), ('HANDOFF', 1))
        self.assertEqual(campaign['conversation_state'], 'HANDOFF')
        self.assertEqual(campaign['last_manual_reply_id'], 'byhand')
        saved = state['local_runtime']['manual_replies']['manual:byhand']
        self.assertEqual(saved['to'], CONTACT)
        self.assertIn('voici le lien', saved['body'])
        self.assertEqual(saved['note'], 'Réponse envoyée à la main')
        self.assertEqual(self.store.scan_scope()['thread_ids'], [])

    def test_second_call_is_a_duplicate_and_does_not_count_twice(self):
        self.store.manual_reply(self.item)
        before = self.store.path.read_bytes()
        self.assertTrue(self.store.manual_reply(self.item)['duplicate'])
        self.assertEqual(before, self.store.path.read_bytes())

    def test_refuses_proof_that_is_not_a_manual_reply(self):
        engine = at(5_400_000, 'reply1', ACCOUNT, True, 'Réponse du moteur.')
        thread = copy.deepcopy(self.thread)
        thread['messages'].append(engine)
        with self.store.transaction() as state:
            state['local_runtime']['events']['k'] = {'thread_id': 't1', 'sent_id': 'reply1', 'phase': 'SAVED'}
        cases = {
            'inconnu du fil': dict(self.item, message_id='ghost'),
            'envoi du moteur': dict(self.item, thread=thread, message_id='reply1'),
            'envoi initial': dict(self.item, message_id='out1'),
            'entrant du prospect': dict(self.item, message_id='in1'),
            'sans preuve': {k: v for k, v in self.item.items() if k != 'evidence'},
            'fil incomplet': dict(self.item, thread=dict(self.thread, complete=False)),
        }
        for label, item in cases.items():
            with self.subTest(label):
                with self.assertRaises(Blocked):
                    self.store.manual_reply(item)
        self.assertEqual(read(self.store.path)['sent'][0]['conversation_state'], 'WAITING_REPLY')

    def test_a_business_stop_is_never_downgraded(self):
        with self.store.transaction() as state:
            state['sent'][0]['conversation_state'] = 'STOPPED'
        self.assertEqual(self.store.manual_reply(self.item)['state'], 'STOPPED')
        state = read(self.store.path)
        self.assertEqual(state['sent'][0]['conversation_state'], 'STOPPED')
        self.assertIn('manual:byhand', state['local_runtime']['manual_replies'])

    def test_refuses_a_reply_addressed_elsewhere_or_predating_the_send(self):
        elsewhere = at(9_000_000, 'other', ACCOUNT, True)
        elsewhere['payload']['headers'] = [h for h in elsewhere['payload']['headers'] if h['name'] != 'To']
        elsewhere['payload']['headers'].append({'name': 'To', 'value': 'someone@example.invalid'})
        early = at(-60_000, 'early', ACCOUNT, True)
        for label, extra in (('autre destinataire', elsewhere), ('anterieur a l envoi', early)):
            with self.subTest(label):
                thread = copy.deepcopy(self.thread)
                thread['messages'].append(extra)
                with self.assertRaises(Blocked):
                    self.store.manual_reply(dict(self.item, thread=thread, message_id=extra['id']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
