import base64
import email
import hashlib
import sys
import unittest
from email import policy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import gmail_smtp
from gtm import addresses, body_text, headers

IMAGE = b'\x89PNG\r\n\x1a\nsynthetic-portrait'
CID = '<portrait-' + hashlib.sha256(IMAGE).hexdigest()[:24] + '@vision-pl.local>'
HTML = ('<!doctype html>\n<html><head><style>.a{color:#29463d}</style></head><body>\n'
        '<!--[if mso]><table><tr><td><![endif]-->\n<p>Bonjour, voici un pilote&#8239;?</p>\n'
        '<img src="cid:' + CID.strip('<>') + '" width="88" height="88" alt="Test Owner">\n'
        '<pre>Test Owner\n+00 000</pre>\n</body></html>\n')


def payload(html=HTML, image=IMAGE, cid=CID):
    return {'mime_type': 'multipart/related', 'parts': [
        {'mime_type': 'text/html', 'charset': 'UTF-8', 'body': {'content': html}},
        {'mime_type': 'image/png', 'filename': 'portrait.png', 'content_disposition': 'inline',
         'content_id': cid,
         'body': {'base64_url_content': base64.urlsafe_b64encode(image).decode().rstrip('=')}}]}


class GmailSmtpTests(unittest.TestCase):
    def intent(self):
        return {'account': 'owner@example.invalid',
                'campaign': {'to': 'lead@example.invalid', 'subject': 'Boutique — marge | Vision P&L', 'body': HTML}}

    def test_exact_html_and_inline_photo_survive_the_wire(self):
        msg = gmail_smtp.build(self.intent(), payload(), 'owner@example.invalid')
        parsed = email.message_from_bytes(msg.as_bytes(policy=policy.SMTP), policy=policy.default)
        engine = gmail_smtp.engine_part(parsed)
        h = headers({'payload': engine})
        self.assertEqual(body_text(engine).strip(), HTML.strip())
        self.assertEqual(h['subject'], 'Boutique — marge | Vision P&L')
        self.assertEqual(addresses(h['from']), {'owner@example.invalid'})
        self.assertEqual(addresses(h['to']), {'lead@example.invalid'})
        self.assertFalse(h.get('cc') or h.get('bcc') or h.get('in-reply-to'))
        image = engine['parts'][1]
        part_headers = {x['name'].lower(): x['value'] for x in image['headers']}
        self.assertEqual(part_headers['content-id'], CID)
        self.assertTrue(part_headers['content-disposition'].startswith('inline'))
        self.assertEqual(image['body']['size'], len(IMAGE))

    def test_portrait_and_brand_logo_travel_together(self):
        logo = b'\x89PNG\r\n\x1a\nsynthetic-logo'
        logo_cid = '<logo-' + hashlib.sha256(logo).hexdigest()[:24] + '@vision-pl.local>'
        html = HTML.replace('<p>', '<img src="cid:' + logo_cid.strip('<>') + '" alt="Boutique">\n<p>', 1)
        prepared = payload(html=html)
        prepared['parts'].append({'mime_type': 'image/png', 'filename': 'logo.png', 'content_disposition': 'inline',
                                  'content_id': logo_cid,
                                  'body': {'base64_url_content': base64.urlsafe_b64encode(logo).decode().rstrip('=')}})
        intent = self.intent()
        intent['campaign']['body'] = html
        msg = gmail_smtp.build(intent, prepared, 'owner@example.invalid')
        parsed = email.message_from_bytes(msg.as_bytes(policy=policy.SMTP), policy=policy.default)
        engine = gmail_smtp.engine_part(parsed)
        self.assertEqual(body_text(engine).strip(), html.strip())
        self.assertEqual([p['body'].get('size') for p in engine['parts'][1:]], [len(IMAGE), len(logo)])

    def test_imap_labels_are_unquoted_and_mapped(self):
        self.assertEqual(gmail_smtp.gmail_labels(r'"\\Sent" "\\Important" "Vision P&L"'),
                         ['IMPORTANT', 'SENT', 'Vision P&L'])
        self.assertEqual(gmail_smtp.gmail_labels(r'\Sent'), ['SENT'])

    def test_changed_html_or_foreign_photo_is_refused(self):
        with self.assertRaises(gmail_smtp.Blocked):
            gmail_smtp.build(self.intent(), payload(html=HTML.replace('pilote', 'produit')), 'owner@example.invalid')
        with self.assertRaises(gmail_smtp.Blocked):
            gmail_smtp.build(self.intent(), payload(image=b'\x89PNG\r\n\x1a\nother'), 'owner@example.invalid')


if __name__ == '__main__':
    unittest.main()
