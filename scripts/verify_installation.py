"""Read-only installation audit. Never replays events, gates, scans or reports."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
from gtm import ROOT, Store, read


def verify(root):
    store = Store(root)
    state = read(store.path)
    checks = {}
    for name, expected in state['local_runtime'].get('source_hashes', {}).items():
        path = store.local / 'originals' / name
        checks['original:' + name] = path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == expected
    originals = list((store.local / 'originals').glob('*.json'))
    if len(originals) == 1:
        original = read(originals[0])
        current = {s['result']['id']: s for s in state['sent']}
        checks['outbound_history_preserved'] = all(
            s['result']['id'] in current and all(current[s['result']['id']].get(k) == s.get(k)
            for k in ('body', 'subject', 'to', 'result', 'actual_from', 'sent_date'))
            for s in original['sent'])
    expected = state['local_runtime']['mode'] == 'live' and all(state['local_runtime']['gates'].values())
    checks['summary_matches_runtime'] = state.get('auto_reply_enabled') == expected
    checks['unique_sent_ids'] = len({(s.get('actual_from'), s['result']['id']) for s in state['sent']}) == len(state['sent'])
    return {'read_only': True, 'ok': all(checks.values()), 'checks': checks, 'status': store.status(),
            'limitations': 'No new connector call, scheduled run or real email delivery is tested.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    result = verify(parser.parse_args().root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    sys.exit(main())
