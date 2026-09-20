"""Durable local journal for one Desktop orchestrator. Never calls Gmail or an LLM.

The agent invokes connectors, persists their evidence and uses these transitions.
SENDING has no automatic retry: external delivery is not transactional with disk.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from email.utils import getaddresses
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
TERMINAL = {'STOPPED', 'BOUNCED', 'HANDOFF', 'BOOKED'}
REPLY_KINDS = {'simple_question', 'interest', 'meeting_request'}
KINDS = REPLY_KINDS | {'refusal', 'permanent_bounce', 'automatic', 'not_now', 'handoff'}

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temp.open('x', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)

class Blocked(RuntimeError):
    pass

@contextmanager
def mutex(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as f:
        f.seek(0, 2)
        if f.tell() == 0:
            f.write(b'0')
            f.flush()
        f.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise Blocked('Another local operation is running') from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == 'nt':
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)

def headers(message):
    return {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}

def addresses(value):
    return {a.lower() for _, a in getaddresses([value]) if a}

def fingerprint(thread):
    return digest(thread['messages'])

def body_text(payload):
    text = payload.get('body', {}).get('content') or ''
    return text + ''.join(body_text(p) for p in (payload.get('parts') or []))

class Store:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.local = self.root / 'local'
        self.path = self.local / 'GTM_Design_Partners_Etat.json'

    def commit(self, state):
        atomic(self.path, state)

    @contextmanager
    def transaction(self):
        with mutex(self.local / 'journal.lock'):
            original = self.path.read_bytes()
            state = json.loads(original.decode('utf-8-sig'))
            yield state
            if self.path.read_bytes() != original:
                raise Blocked('Journal changed outside the lock; reload before retry')
            state['local_runtime']['revision'] += 1
            state['local_runtime']['updated_at'] = now()
            backup = self.local / 'backups' / ('journal-' + uuid.uuid4().hex + '.json')
            atomic(backup, json.loads(original.decode('utf-8-sig')))
            self.commit(state)

    def status(self):
        state = read(self.path)
        rt = state['local_runtime']
        return {'mode': rt['mode'], 'emergency_stop': (self.local / 'STOP').exists(),
                'revision': rt['revision'], 'historical_sent': len(state['sent']),
                'events': len(rt['events']), 'pending_notifications': sum(not n.get('delivered_at') for n in rt['notifications'].values()),
                'uncertain_sends': [k for k, e in rt['events'].items() if e['phase'] == 'SENDING'],
                'activation_blockers': [k for k,v in rt['gates'].items() if not v],
                'last_completed_scan': rt.get('last_completed_scan')}

    def campaign(self, state, account, thread_id):
        matches = [s for s in state['sent'] if s.get('actual_from') == account
                   and s['result']['thread_id'] == thread_id]
        if len(matches) != 1:
            raise Blocked('No unique journaled send for this account and thread')
        return matches[0]

    def inspect_thread(self, state, account, thread):
        if account != state['preferred_sender']:
            raise Blocked('Wrong connected Gmail account')
        if thread.get('complete') is not True:
            raise Blocked('Full thread coverage not established')
        campaign = self.campaign(state, account, thread['id'])
        messages = thread['messages']
        initial = next((m for m in messages if m['id'] == campaign['result']['id']), None)
        if not initial or 'SENT' not in initial.get('label_ids', []):
            raise Blocked('Journaled initial outbound missing from thread')
        ih = headers(initial)
        if addresses(ih.get('from', '')) != {account} or addresses(ih.get('to', '')) != {campaign['to'].lower()}:
            raise Blocked('Initial outbound identity does not match the campaign')
        known = {campaign['result']['id']} | {e.get('sent_id') for e in state['local_runtime']['events'].values() if e.get('thread_id') == thread['id']}
        manual = any(m['id'] not in known and ('SENT' in m.get('label_ids', []) or account in addresses(headers(m).get('from', ''))) for m in messages)
        return campaign, manual

    def ingest(self, item):
        account, thread = item['account'], item['thread']
        key = account + ':' + item['inbound_id']
        with self.transaction() as state:
            rt = state['local_runtime']
            if key in rt['events']:
                return {'duplicate': True, 'key': key, 'phase': rt['events'][key]['phase']}
            campaign, manual = self.inspect_thread(state, account, thread)
            message = item.get('detached_message') or next((m for m in thread['messages'] if m['id'] == item['inbound_id']), None)
            if not message or message['id'] != item['inbound_id']:
                raise Blocked('Inbound message missing from exact thread')
            h = headers(message)
            detached = message['thread_id'] != thread['id']
            if detached:
                initial = next(m for m in thread['messages'] if m['id'] == campaign['result']['id'])
                ref = headers(initial).get('message-id')
                refs = (h.get('references', '') + ' ' + h.get('in-reply-to', '')).split()
                if not ref or ref not in refs:
                    raise Blocked('Detached message has no exact RFC reference to journaled send')
            if 'SENT' in message.get('label_ids', []) or account in addresses(h.get('from', '')):
                return {'ignored': 'outgoing'}
            kind = item['classification']
            if kind not in KINDS:
                kind = 'handoff'
            if h.get('auto-submitted', 'no').lower() != 'no' and kind != 'permanent_bounce':
                kind = 'automatic'
            if detached and kind in REPLY_KINDS:
                kind = 'handoff'
            # Unknown correspondents never receive automatic replies.
            if campaign['to'].lower() not in addresses(h.get('from', '')) and kind not in {'automatic', 'permanent_bounce'}:
                kind = 'handoff'
            current = campaign.get('conversation_state', 'WAITING_REPLY')
            if manual:
                current = 'HANDOFF'
            if kind == 'refusal':
                current = 'STOPPED'
            elif kind == 'permanent_bounce' and current != 'STOPPED':
                current = 'BOUNCED'
            elif current not in TERMINAL and (kind == 'handoff' or campaign.get('auto_reply_count', 0) >= 3):
                current = 'HANDOFF'
            campaign['conversation_state'] = current
            event = {'account': account, 'thread_id': thread['id'], 'inbound_id': message['id'],
                     'inbound_thread_id': message['thread_id'], 'inbound_rfc_id': h.get('message-id'),
                     'classification': kind, 'phase': 'DETECTED', 'detected_at': now(),
                     'thread_fingerprint': fingerprint(thread), 'evidence': item.get('evidence', ''),
                     'notification_required': current in {'HANDOFF', 'BOUNCED'}}
            if current in TERMINAL or kind in {'automatic', 'not_now'}:
                event['phase'] = 'SAVED'
                event['saved_at'] = now()
            rt['events'][key] = event
            if event['notification_required']:
                rt['notifications'].setdefault(key, {'kind': current, 'event_key': key, 'created_at': now()})
            return {'key': key, 'phase': event['phase'], 'state': current}

    def prepare(self, item):
        with self.transaction() as state:
            e = state['local_runtime']['events'][item['key']]
            if e['phase'] != 'DETECTED' or e['classification'] not in REPLY_KINDS:
                raise Blocked('Event not eligible for reply preparation')
            c = self.campaign(state, e['account'], e['thread_id'])
            if c['conversation_state'] in TERMINAL:
                raise Blocked('Conversation suspended')
            if any(other is not e and other['thread_id'] == e['thread_id'] and other['phase'] in {'CLAIMED', 'SENDING'} for other in state['local_runtime']['events'].values()):
                raise Blocked('Another event already owns this thread')
            if state['signature'] not in item['body']:
                raise Blocked('Required signature missing')
            if not e.get('inbound_rfc_id'):
                raise Blocked('Inbound RFC Message-ID required for reply proof')
            # Reply destination cannot be supplied/changed by email instructions.
            e.update(phase='CLAIMED', claim=uuid.uuid4().hex, body=item['body'], to=c['to'], subject=item['subject'])
            return {'key': item['key'], 'claim': e['claim'], 'phase': e['phase']}

    def arm(self, item):
        blocked = None
        result = None
        with self.transaction() as state:
            rt = state['local_runtime']
            e = rt['events'][item['key']]
            if (self.local / 'STOP').exists() or rt['mode'] != 'live' or not all(rt['gates'].values()):
                raise Blocked('Live sending disabled; verify all activation gates')
            if e['phase'] != 'CLAIMED' or item['claim'] != e['claim']:
                raise Blocked('Claim already consumed or invalid')
            checked = datetime.fromisoformat(item['checked_at'])
            age = (datetime.now(timezone.utc) - checked).total_seconds()
            if not 0 <= age <= 60:
                raise Blocked('Profile and thread reads must be less than 60 seconds old')
            c, manual = self.inspect_thread(state, item['profile_email'], item['thread'])
            if item['thread']['id'] != e['thread_id']:
                raise Blocked('Wrong refreshed thread')
            if manual:
                c['conversation_state'] = 'HANDOFF'
                e['phase'] = 'SAVED'
                rt['notifications'].setdefault(item['key'], {'kind': 'HANDOFF', 'event_key': item['key'], 'created_at': now()})
                blocked = 'Manual reply detected; conversation handed off'
            elif c['conversation_state'] in TERMINAL or c.get('auto_reply_count', 0) >= 3:
                blocked = 'Conversation suspended or reply limit reached'
            elif fingerprint(item['thread']) != e['thread_fingerprint']:
                blocked = 'Thread changed; reclassify before replying'
            else:
                if e['classification'] == 'meeting_request':
                    cal = item.get('calendly', {})
                    if cal.get('active') is not True or cal.get('scheduling_url') != state['calendly']['selected_event_url'] or cal['scheduling_url'] not in e['body']:
                        raise Blocked('Selected Calendly link must be checked before reply')
                # Durable intent BEFORE connector call; a crash cannot cause automatic retry.
                e.update(phase='SENDING', armed_at=now(), expected_body_hash=digest(e['body']))
                result = {'to': e['to'], 'subject': e['subject'], 'body': e['body'], 'reply_message_id': e['inbound_id'], 'claim': e['claim']}
        if blocked:
            raise Blocked(blocked)
        return result

    def receipt(self, item):
        # Check evidence, write recovery receipt, then update the canonical journal.
        with mutex(self.local / 'journal.lock'):
            state = read(self.path)
            e = state['local_runtime']['events'][item['key']]
            self.validate_receipt(state, e, item)
            receipt_path = self.local / 'receipts' / (digest(item['key']) + '.json')
            if receipt_path.exists() and read(receipt_path) != item:
                raise Blocked('Conflicting receipt; inspect Gmail, do not overwrite')
            atomic(receipt_path, item)
        return self.recover()

    def validate_receipt(self, state, e, item):
        m = item['message']
        if e['phase'] not in {'SENDING', 'SAVED'} or item['claim'] != e.get('claim'):
            raise Blocked('No matching send intent')
        if item['account'] != state['preferred_sender'] or m['thread_id'] != e['thread_id'] or 'SENT' not in m.get('label_ids', []):
            raise Blocked('Receipt account/thread/SENT mismatch')
        h = headers(m)
        if not m.get('internal_date') or datetime.fromtimestamp(int(m['internal_date']) / 1000, timezone.utc) < datetime.fromisoformat(e['armed_at']):
            raise Blocked('Receipt predates the send intent')
        if h.get('in-reply-to') != e.get('inbound_rfc_id'):
            raise Blocked('Receipt does not reference the exact inbound RFC message')
        if addresses(h.get('from', '')) != {state['preferred_sender']} or addresses(h.get('to', '')) != {e['to'].lower()}:
            raise Blocked('Receipt sender/recipient mismatch')
        if h.get('cc') or h.get('bcc') or h.get('subject') != e['subject']:
            raise Blocked('Receipt headers mismatch')
        if body_text(m['payload']).strip() != e['body'].strip():
            raise Blocked('Receipt body mismatch')
        if e.get('sent_id') and e['sent_id'] != m['id']:
            raise Blocked('Conflicting Gmail message proof')

    def recover(self):
        recovered = []
        with self.transaction() as state:
            for path in sorted((self.local / 'receipts').glob('*.json')):
                item = read(path)
                e = state['local_runtime']['events'].get(item['key'])
                if not e:
                    raise Blocked('Receipt missing corresponding intent; restore newer backup')
                self.validate_receipt(state, e, item)
                if e.get('sent_id'):
                    continue
                e.update(sent_id=item['message']['id'], sent_confirmed_at=now(), phase='SAVED', saved_at=now())
                c = self.campaign(state, e['account'], e['thread_id'])
                c['auto_reply_count'] = c.get('auto_reply_count', 0) + 1
                c['last_processed_inbound_id'] = e['inbound_id']
                if c['conversation_state'] not in TERMINAL:
                    c['conversation_state'] = 'PENDING_BOOKING' if e['classification'] == 'meeting_request' else 'QUALIFYING'
                recovered.append(item['key'])
        return {'recovered': recovered}

    def scan_page(self, item):
        with self.transaction() as state:
            rt = state['local_runtime']
            scan = rt.get('scan')
            if not scan or scan.get('complete'):
                if item.get('page_token'):
                    raise Blocked('First page requires null cursor')
                scan = {'id': item['scan_id'], 'query': item['query'], 'started_at': item['started_at'], 'next_page_token': None, 'message_ids': [], 'pages': []}
                rt['scan'] = scan
            if item['scan_id'] != scan['id'] or item['query'] != scan['query'] or item.get('page_token') != scan['next_page_token']:
                raise Blocked('Scan cursor or query mismatch')
            token = item.get('next_page_token')
            if token and token in scan['pages']:
                raise Blocked('Repeated pagination token')
            scan['pages'].append(item.get('page_token'))
            scan['message_ids'] = sorted(set(scan['message_ids']) | set(item['message_ids']))
            scan['next_page_token'] = token
            scan['complete'] = token is None
            if scan['complete']:
                rt['last_completed_scan'] = scan['started_at']
            return deepcopy(scan)

    def mode(self, mode):
        if mode == 'stop':
            (self.local / 'STOP').write_text(now(), encoding='utf-8')
        with self.transaction() as state:
            rt = state['local_runtime']
            if mode == 'live' and not all(rt['gates'].values()):
                raise Blocked('Activation gates unresolved')
            rt['mode'] = 'paused' if mode == 'stop' else mode
        if mode in {'monitor', 'live'}:
            (self.local / 'STOP').unlink(missing_ok=True)
        return self.status()

    def notify_ack(self, key):
        with self.transaction() as state:
            state['local_runtime']['notifications'][key]['delivered_at'] = now()
        return {'notification_saved': key}

    def release(self, key):
        with self.transaction() as state:
            e = state['local_runtime']['events'][key]
            if e['phase'] != 'CLAIMED':
                raise Blocked('Only unsent claims can be released; never retry SENDING')
            e['phase'] = 'DETECTED'
            e.pop('claim', None)
        return {'released': key}

    def booking(self, item):
        with self.transaction() as state:
            c = self.campaign(state, item['account'], item['thread_id'])
            event, invitee = item['event'], item['invitee']
            if event.get('status') != 'active' or event.get('event_type') != state['calendly']['selected_event_uri']:
                raise Blocked('Active selected Calendly event required')
            if invitee.get('status') != 'active' or invitee.get('event') != event.get('uri') or invitee.get('email', '').lower() != c['to'].lower():
                raise Blocked('Confirmed invitee must match campaign recipient')
            if not event.get('start_time') or not invitee.get('timezone'):
                raise Blocked('Confirmed slot and timezone required')
            if state['calendly']['user_uri'] not in {m.get('user') for m in event.get('event_memberships', [])}:
                raise Blocked('Wrong Calendly host')
            c['calendly_event_uri'] = event['uri']
            c['booking_evidence'] = item
            if c.get('conversation_state') not in {'STOPPED', 'BOUNCED', 'HANDOFF'}:
                c['conversation_state'] = 'BOOKED'
            key = 'booking:' + event['uri'] + ':' + invitee['email'].lower()
            state['local_runtime']['notifications'].setdefault(key, {'kind':'BOOKED','created_at':now(),'event_key':key})
        return {'confirmed_booking': True}

    def gate(self, item):
        with self.transaction() as state:
            rt = state['local_runtime']
            name = item['name']
            if name not in rt['gates'] or not item.get('evidence') or item.get('verified') is not True:
                raise Blocked('Known gate and actual verification evidence required')
            rt['gates'][name] = True
            rt.setdefault('gate_evidence', {})[name] = {'evidence':item['evidence'],'at':now()}
        return self.status()

    def restore(self, backup):
        backup = Path(backup).resolve()
        if backup.parent != (self.local / 'backups').resolve():
            raise Blocked('Restore must use a journal backup from this installation')
        restored = read(backup)
        if 'local_runtime' not in restored:
            raise Blocked('Not a compatible runtime backup')
        # Keep receipts and force monitor mode. Recovery must succeed before activation.
        with self.transaction() as current:
            restored['local_runtime']['mode'] = 'monitor'
            restored['local_runtime']['gates']['scheduled_run_verified'] = False
            current.clear()
            current.update(restored)
        return self.recover()

def initialize(root, journal, workbook, workflow):
    store = Store(root)
    if store.path.exists():
        raise Blocked('Already initialized; source import never overwrites live state')
    state = read(journal)
    sent = state['sent']
    keys = [(s.get('actual_from') or 'historical_mailbox', s['result']['id']) for s in sent]
    if len(keys) != len(set(keys)):
        raise Blocked('Duplicate outbound evidence in import')
    for path in (journal, workbook, workflow):
        target = store.local / 'originals' / Path(path).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    shutil.copy2(workbook, store.local / 'Design_partners_FR_CH_BE.xlsx')
    shutil.copy2(workflow, store.local / 'WORKFLOW_SOURCE.md')
    state['local_runtime'] = {'version': 1, 'revision': 0, 'mode': 'monitor', 'created_at': now(),
        'events': {}, 'notifications': {}, 'last_completed_scan': None,
        'gates': {'astra_selected': False, 'old_automation_cutover': False, 'scheduled_run_verified': False,
                  'gmail_write_verified': False, 'legacy_coverage_resolved': False},
        'source_hashes': {Path(p).name: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (journal,workbook,workflow)}}
    state['auto_reply_enabled'] = False
    atomic(store.path, state)
    return store.status()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('init')
    for name in ('journal', 'workbook', 'workflow'):
        p.add_argument('--' + name, required=True)
    for name in ('status','recover','stop','monitor','live'):
        sub.add_parser(name)
    for name in ('ingest','prepare','arm','receipt','scan-page','booking','gate'):
        sub.add_parser(name).add_argument('input', type=Path)
    sub.add_parser('notify-ack').add_argument('key')
    sub.add_parser('release').add_argument('key')
    sub.add_parser('restore').add_argument('backup', type=Path)
    args = parser.parse_args()
    store = Store(args.root)
    try:
        if args.cmd == 'init':
            result = initialize(args.root,args.journal,args.workbook,args.workflow)
        elif args.cmd in {'stop','monitor','live'}:
            result = store.mode(args.cmd)
        elif args.cmd in {'status','recover'}:
            result = getattr(store,args.cmd)()
        elif args.cmd == 'notify-ack':
            result = store.notify_ack(args.key)
        elif args.cmd == 'release':
            result = store.release(args.key)
        elif args.cmd == 'restore':
            result = store.restore(args.backup)
        else:
            result = getattr(store,args.cmd.replace('-','_'))(read(args.input))
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (Blocked, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'blocked': str(exc)},ensure_ascii=False),file=sys.stderr)
        return 2
    return 0

if __name__ == '__main__':
    sys.exit(main())
