"""Exact MIME initial outreach over Gmail SMTP, with an IMAP read-back for the receipt.

Only an intent already armed by `gtm.py outbound-arm` (phase SENDING, same claim) can be
sent, exactly once: an attempt marker is written before the SMTP call and is never
cleared, so a crash leaves an uncertain send to reconcile, not a retry. The app password
is decrypted by Windows for the current user from local/gmail-runtime/smtp-credential.xml
(Export-Clixml); it is never printed, logged or written here.

  check --to ADDRESS             fresh account + duplicate read, for outbound-arm
  send  --key K --claim C --payload P
  fetch --key K --claim C        read the sent message back, write the receipt input
  design-test --to A --subject "[TEST] ..." --payload P
                                 design test to one of Jonathan's own addresses (private
                                 allowlist), never a prospect, never journaled
"""
import argparse
import base64
import email
import hashlib
import imaplib
import json
import re
import smtplib
import ssl
import subprocess
import sys
import time
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / 'local'
JOURNAL = LOCAL / 'GTM_Design_Partners_Etat.json'
CREDENTIAL = LOCAL / 'gmail-runtime' / 'smtp-credential.xml'
EVIDENCE = LOCAL / 'outbound-smtp'
TEST_RECIPIENTS = LOCAL / 'gmail-runtime' / 'test-recipients.json'  # Jonathan's own addresses, outside Git
SMTP_HOST, IMAP_HOST = 'smtp.gmail.com', 'imap.gmail.com'
FREEMAIL = {'gmail.com', 'googlemail.com', 'hotmail.com', 'hotmail.fr', 'outlook.com', 'outlook.fr', 'live.com',
            'live.fr', 'msn.com', 'yahoo.com', 'yahoo.fr', 'icloud.com', 'me.com', 'orange.fr', 'wanadoo.fr',
            'free.fr', 'sfr.fr', 'laposte.net', 'bluewin.ch', 'gmx.ch', 'gmx.fr', 'skynet.be', 'telenet.be', 'proton.me'}
LABELS = {'\\Sent': 'SENT', '\\Inbox': 'INBOX', '\\Important': 'IMPORTANT',
          '\\Starred': 'STARRED', '\\Draft': 'DRAFT', '\\Spam': 'SPAM', '\\Trash': 'TRASH'}


class Blocked(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8', newline='\n') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def credential():
    script = ("$c = Import-Clixml -LiteralPath $env:GTM_SMTP_CREDENTIAL; "
              "[Console]::Out.Write($c.UserName + [char]10 + $c.GetNetworkCredential().Password)")
    env = {'GTM_SMTP_CREDENTIAL': str(CREDENTIAL), 'SystemRoot': 'C:\\Windows'}
    out = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command', script],
                         capture_output=True, text=True, env=env, timeout=60)
    if out.returncode or '\n' not in out.stdout:
        raise Blocked('Gmail app password unavailable for this Windows account')
    user, secret = out.stdout.split('\n', 1)
    secret = secret.strip().replace(' ', '')
    state = read(JOURNAL)
    if user.strip().lower() != state['preferred_sender'] or not secret:
        raise Blocked('Stored credential does not belong to the journal sender')
    return state['preferred_sender'], secret


def imap_session(user, secret):
    imap = imaplib.IMAP4_SSL(IMAP_HOST, ssl_context=ssl.create_default_context())
    imap.login(user, secret)
    return imap


def folders(imap):
    """Map special-use flags (\\All, \\Junk, \\Trash) to their localized mailbox names."""
    found = {}
    for line in imap.list()[1]:
        text = line.decode('utf-8', 'replace')
        match = re.match(r'\((?P<flags>[^)]*)\) "(?:[^"]*)" (?P<name>.+)$', text)
        if match:
            for flag in ('\\All', '\\Junk', '\\Trash'):
                if flag in match.group('flags').split():
                    found[flag] = match.group('name')
    if '\\All' not in found:
        raise Blocked('Gmail All Mail folder not found over IMAP')
    return found


def raw_search(imap, mailbox, query):
    typ, _ = imap.select(mailbox, readonly=True)
    if typ != 'OK':
        raise Blocked('Cannot open ' + mailbox)
    typ, data = imap.uid('SEARCH', 'X-GM-RAW', '"' + query.replace('"', '') + '"')
    if typ != 'OK':
        raise Blocked('IMAP search failed')
    return data[0].split() if data and data[0] else []


def gmail_ids(imap, uids):
    ids = []
    for uid in uids:
        typ, data = imap.uid('FETCH', uid, '(X-GM-MSGID)')
        match = re.search(rb'X-GM-MSGID (\d+)', data[0] if isinstance(data[0], bytes) else data[0][0])
        ids.append(format(int(match.group(1)), 'x'))
    return ids


def summaries(imap, uids, folder):
    """From, To, Subject and Date of each message found, read without marking it read,
    so that a confirmed new first message can be preceded by a real review."""
    out = []
    for uid in uids:
        typ, data = imap.uid('FETCH', uid, '(X-GM-MSGID BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])')
        if typ != 'OK' or not data or not isinstance(data[0], tuple):
            continue
        meta, raw = data[0]
        match = re.search(rb'X-GM-MSGID (\d+)', meta)
        head = email.message_from_bytes(raw, policy=policy.default)
        out.append({'id': format(int(match.group(1)), 'x') if match else None, 'folder': folder,
                    **{k: str(head.get(k, '')) for k in ('from', 'to', 'subject', 'date')}})
    return out


def check(args):
    """Fresh proof of the logged-in account and of the absence of any correspondence."""
    user, secret = credential()
    domain = args.to.split('@', 1)[1].lower()
    # A shop's own domain is searched whole; a free mailbox domain would match most of the inbox.
    target = args.to.lower() if domain in FREEMAIL else domain
    query = '{from:%s to:%s cc:%s bcc:%s}' % (target, target, target, target)
    imap = imap_session(user, secret)
    try:
        boxes = folders(imap)
        ids, messages = [], []
        for flag in ('\\All', '\\Junk', '\\Trash'):
            if flag in boxes:
                uids = raw_search(imap, boxes[flag], query)
                ids += gmail_ids(imap, uids)
                messages += summaries(imap, uids, flag)
    finally:
        imap.logout()
    return {'account': user, 'checked_at': now(), 'query': query, 'folders': sorted(boxes),
            'duplicate_check': {'message_ids': sorted(set(ids)), 'next_page_token': None},
            'messages': messages}


def intent(key, claim):
    e = read(JOURNAL)['local_runtime'].get('outbound_intents', {}).get(key)
    if not e or e.get('claim') != claim:
        raise Blocked('No armed intent for this key and claim')
    return e


def b64url(value):
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def build(e, payload, user):
    c = e['campaign']
    if payload.get('mime_type') == 'text/html':
        html_part, images = payload, []
    elif payload.get('mime_type') == 'multipart/related' and len(payload.get('parts', [])) >= 2:
        html_part, images = payload['parts'][0], payload['parts'][1:]
    else:
        raise Blocked('Unexpected prepared MIME structure')
    html = html_part['body']['content']
    if html_part['mime_type'] != 'text/html' or html != c['body']:
        raise Blocked('Prepared HTML differs from the armed campaign body')
    inline = []
    for part in images:
        data, cid = b64url(part['body']['base64_url_content']), part['content_id']
        name = cid.strip('<>').split('@', 1)[0]
        if not re.fullmatch(r'(portrait|logo)-' + hashlib.sha256(data).hexdigest()[:24], name) or \
                ('cid:' + cid.strip('<>')) not in html:
            raise Blocked('Inline image does not match its Content-ID')
        inline.append((part, data, cid))
    msg = EmailMessage(policy=policy.SMTP)
    msg['From'] = 'Jonathan Naal <%s>' % user
    msg['To'] = c['to']
    msg['Subject'] = c['subject']
    msg['Date'] = formatdate(localtime=True)
    msg['Message-ID'] = make_msgid(domain='gmail.com')
    msg.set_content(html, subtype='html', charset='utf-8', cte='quoted-printable')
    for part, data, cid in inline:
        maintype, subtype = part['mime_type'].split('/')
        msg.add_related(data, maintype=maintype, subtype=subtype, cid=cid,
                        filename=part['filename'], disposition='inline')
    return msg


def send(args):
    e = intent(args.key, args.claim)
    if e['phase'] != 'SENDING':
        raise Blocked('Intent is not in SENDING')
    folder = EVIDENCE / args.key.replace(':', '-')
    if (folder / 'attempt.json').exists():
        raise Blocked('A send was already attempted for this intent: reconcile, never retry')
    user, secret = credential()
    if e['account'] != user:
        raise Blocked('Intent account differs from the stored credential')
    msg = build(e, read(args.payload), user)
    if (LOCAL / 'STOP').exists():
        raise Blocked('local/STOP present')
    write_new(folder / 'attempt.json', {'key': args.key, 'claim': args.claim, 'to': e['campaign']['to'],
                                        'message_id_header': msg['Message-ID'], 'payload': str(args.payload),
                                        'attempted_at': now()})
    result = smtp_send(user, secret, msg, e['campaign']['to'])
    result.update(key=args.key, message_id_header=msg['Message-ID'], finished_at=now())
    write_new(folder / 'send-result.json', result)
    return result


def smtp_send(user, secret, msg, to):
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, 465, context=ssl.create_default_context(), timeout=120) as smtp:
            smtp.login(user, secret)
            refused = smtp.send_message(msg, from_addr=user, to_addrs=[to])
        return {'status': 'ACCEPTED' if not refused else 'REFUSED',
                'refused': {k: list(map(str, v)) for k, v in refused.items()}}
    except Exception as exc:  # the message may or may not have left: uncertain, never retried
        return {'status': 'UNCERTAIN', 'error': type(exc).__name__ + ': ' + str(exc)}


def design_test(args):
    """A rendered design test for one of Jonathan's own addresses: never a prospect, never journaled."""
    allowed = {a.lower() for a in read(TEST_RECIPIENTS)} if TEST_RECIPIENTS.exists() else set()
    to = args.to.lower()
    if to not in allowed:
        raise Blocked('Design tests only go to an address listed in local/gmail-runtime/test-recipients.json')
    if not args.subject.startswith('[TEST]'):
        raise Blocked('Design test subject must start with [TEST]')
    state = read(JOURNAL)
    if any(s['to'].lower() == to for s in state['sent']) or \
            any(str(r.get('Email professionnel') or '').lower() == to for r in state['records']):
        raise Blocked('This address belongs to the campaign journal')
    payload = read(args.payload)
    html = (payload['parts'][0] if payload.get('parts') else payload)['body']['content']
    user, secret = credential()
    msg = build({'campaign': {'to': args.to, 'subject': args.subject, 'body': html}}, payload, user)
    folder = LOCAL / 'email-design' / 'tests' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    write_new(folder / 'attempt.json', {'to': args.to, 'subject': args.subject, 'payload': str(args.payload),
                                        'message_id_header': msg['Message-ID'], 'attempted_at': now()})
    result = smtp_send(user, secret, msg, args.to)
    result.update(message_id_header=msg['Message-ID'], finished_at=now(), evidence=str(folder))
    write_new(folder / 'send-result.json', result)
    return result


def engine_part(part):
    d = {'mime_type': part.get_content_type(), 'filename': part.get_filename() or '',
         'headers': [{'name': k, 'value': str(v)} for k, v in part.items()], 'body': {}}
    if part.is_multipart():
        d['parts'] = [engine_part(p) for p in part.iter_parts()]
    elif part.get_content_maintype() == 'text':
        d['body'] = {'content': part.get_content().replace('\r\n', '\n')}
    else:
        data = part.get_payload(decode=True) or b''
        d['body'] = {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
    return d


def gmail_labels(text):
    """X-GM-LABELS items, IMAP-unquoted, with system labels named as in the Gmail API."""
    labels = set()
    for item in re.findall(r'"(?:[^"\\]|\\.)*"|\S+', text):
        if item.startswith('"'):
            item = re.sub(r'\\(.)', r'\1', item[1:-1])
        labels.add(LABELS.get(item, item))
    return sorted(labels)


def fetch(args):
    e = intent(args.key, args.claim)
    folder = EVIDENCE / args.key.replace(':', '-')
    sent = read(folder / 'send-result.json')
    user, secret = credential()
    imap = imap_session(user, secret)
    try:
        box = folders(imap)['\\All']
        uids = []
        for _ in range(12):
            uids = raw_search(imap, box, 'rfc822msgid:' + sent['message_id_header'].strip('<>'))
            if uids:
                break
            time.sleep(5)
        if len(uids) != 1:
            raise Blocked('Sent message not found exactly once (%d)' % len(uids))
        typ, data = imap.uid('FETCH', uids[0], '(X-GM-MSGID X-GM-THRID X-GM-LABELS INTERNALDATE BODY.PEEK[])')
    finally:
        imap.logout()
    meta, raw = data[0][0].decode('utf-8', 'replace'), data[0][1]
    msgid = format(int(re.search(r'X-GM-MSGID (\d+)', meta).group(1)), 'x')
    thrid = format(int(re.search(r'X-GM-THRID (\d+)', meta).group(1)), 'x')
    label_ids = gmail_labels(re.search(r'X-GM-LABELS \(([^)]*)\)', meta).group(1))
    internal = time.mktime(imaplib.Internaldate2tuple(meta.encode()))
    parsed = email.message_from_bytes(raw, policy=policy.default)
    message = {'id': msgid, 'thread_id': thrid, 'label_ids': label_ids,
               'internal_date': str(int(internal * 1000)), 'payload': engine_part(parsed),
               'size_estimate': len(raw)}
    item = {'key': args.key, 'claim': args.claim, 'account': user, 'message': message,
            'evidence': {'channel': 'Gmail IMAP (X-GM-MSGID/THRID/LABELS, INTERNALDATE, BODY.PEEK[])',
                         'raw_sha256': hashlib.sha256(raw).hexdigest(), 'read_at': now(),
                         'message_id_header': sent['message_id_header']}}
    path = folder / 'receipt-input.json'
    if not path.exists():
        write_new(path, item)
    return {'receipt_input': str(path), 'id': msgid, 'thread_id': thrid, 'labels': label_ids}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    sub.add_parser('check').add_argument('--to', required=True)
    p = sub.add_parser('design-test')
    p.add_argument('--to', required=True)
    p.add_argument('--subject', required=True)
    p.add_argument('--payload', type=Path, required=True)
    for name in ('send', 'fetch'):
        p = sub.add_parser(name)
        p.add_argument('--key', required=True)
        p.add_argument('--claim', required=True)
        if name == 'send':
            p.add_argument('--payload', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = {'check': check, 'send': send, 'fetch': fetch, 'design-test': design_test}[args.cmd](args)
    except (Blocked, OSError, KeyError, imaplib.IMAP4.error, smtplib.SMTPException) as exc:
        print(json.dumps({'blocked': type(exc).__name__ + ': ' + str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
