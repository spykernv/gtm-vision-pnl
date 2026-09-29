import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from render_email import render, build_payload
from gtm import body_text
from test_outbound import OutboundTests as Harness


class EmailTemplateTests(unittest.TestCase):
    def data(self):
        return dict(subject='Pilote', preheader='Un échange.', eyebrow='PILOTE',
                    headline='Votre marge.', salutation='Bonjour,', observation='Un fait sourcé.',
                    question='Une question ?', pilot_title='Le pilote', pilot_body='Exploratoire.',
                    invitation='Échangeons.', cta_label='Répondre',
                    cta_url='mailto:owner@example.invalid', closing='À bientôt,',
                    signature='Test Owner\n+00 000', optout='Dites-moi si je dois arrêter.')

    def test_html_roundtrip_through_existing_outbound_protocol(self):
        harness = Harness()
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        markup, _ = render(self.data())
        harness.item['campaign']['body'] = markup
        receipt = harness.arm_receipt()
        receipt['message']['payload']['mime_type'] = 'text/html'
        harness.store.outbound_receipt(receipt)
        saved = json.loads(harness.store.path.read_text(encoding='utf-8'))
        self.assertEqual(saved['sent'][0]['body'], markup)
        self.assertEqual(saved['sent'][0]['conversation_state'], 'WAITING_REPLY')

    def test_untrusted_content_cannot_inject_html(self):
        data = self.data()
        data['observation'] = '<script>alert(1)</script><a href="https://evil.example.invalid">link</a>'
        markup, text = render(data)
        self.assertNotIn('<script>', markup)
        self.assertIn('&lt;script&gt;', markup)
        self.assertEqual(markup.count('<a '), 1)
        self.assertIn(data['observation'], text)

    def test_inline_photo_keeps_exact_receipt_body_and_postscript(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'portrait.png').write_bytes(b'\x89PNG\r\n\x1a\nsynthetic-test-bytes')
            data = self.data()
            data.update(portrait_path='portrait.png', portrait_alt='Test Owner', postscript='P.-S. Texte exact :)')
            with patch('render_email.ROOT', root), patch('render_email.ASSETS', root):
                markup, plain = render(data)
                payload = build_payload(markup, data)
            self.assertEqual(body_text(payload), markup)
            self.assertEqual(payload['mime_type'], 'multipart/related')
            image_part = payload['parts'][1]
            self.assertEqual(image_part['content_disposition'], 'inline')
            self.assertIn('cid:' + image_part['content_id'].strip('<>'), markup)
            self.assertIn(data['postscript'], markup)
            self.assertIn(data['postscript'], plain)
            harness = Harness()
            harness.setUp()
            self.addCleanup(harness.doCleanups)
            harness.item['campaign']['body'] = markup
            receipt = harness.arm_receipt()
            payload['parts'][0]['headers'] = []
            payload['headers'] = receipt['message']['payload']['headers']
            receipt['message']['payload'] = payload
            harness.store.outbound_receipt(receipt)
            self.assertFalse(harness.store.status()['uncertain_sends'])

    def test_unsafe_links_and_unresolved_fields_refused(self):
        for value in ['javascript:alert(1)', 'data:text/html,foo', 'https://example.invalid/\nheader']:
            data = self.data()
            data['cta_url'] = value
            with self.assertRaises(ValueError):
                render(data)
        data = self.data()
        data['salutation'] = 'Bonjour {{prenom}}'
        with self.assertRaises(ValueError):
            render(data)


if __name__ == '__main__':
    unittest.main()
