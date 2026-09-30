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
                    signature='Test Owner\n+00 000', optout='Dites-moi si je dois arrêter.',
                    brand_name='Boutique Test')

    def test_masthead_names_the_brand_and_falls_back_to_the_descriptor(self):
        markup, _ = render(self.data())
        self.assertIn('P&amp;L</span></span> <span style="white-space:nowrap;"><span style="color:#9a9e84;">×</span> '
                      'Boutique Test</span></td>', markup)
        self.assertIn('MARGE &amp; COÛTS', markup)
        self.assertNotIn('MASTHEAD_RIGHT', markup)
        data = self.data()
        del data['brand_name']
        with self.assertRaises(ValueError):
            render(data)

    def test_brand_logo_replaces_the_descriptor_as_an_inline_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            logo = b'\x89PNG\r\n\x1a\n' + b'\x00\x00\x00\rIHDR' + (356).to_bytes(4, 'big') + (72).to_bytes(4, 'big') + b'synthetic'
            (root / 'logo.png').write_bytes(logo)
            data = self.data()
            data['brand_logo_path'] = 'logo.png'
            with patch('render_email.ROOT', root), patch('render_email.LOGOS', root):
                markup, _ = render(data)
                payload = build_payload(markup, data)
        self.assertNotIn('MARGE &amp; COÛTS', markup)
        self.assertIn('width="178" height="36" alt="Boutique Test"', markup)
        self.assertEqual(body_text(payload), markup)
        part = payload['parts'][1]
        self.assertTrue(part['content_id'].startswith('<logo-'))
        self.assertIn('cid:' + part['content_id'].strip('<>'), markup)

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

    def test_writing_rules_of_30_09(self):
        markup, _ = render(self.data())
        self.assertIn('>CEO Vision P&amp;L</p>', markup)
        self.assertNotIn('—', markup)
        for key in ('subject', 'observation', 'invitation', 'signature'):
            data = self.data()
            data[key] = data[key] + ' — suite'
            with self.assertRaises(ValueError):
                render(data)


if __name__ == '__main__':
    unittest.main()
