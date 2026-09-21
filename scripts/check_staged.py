"""Reject private artifacts, contact data and obvious secrets in staged files."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
ALLOWED_ROOT={'.gitignore','.gitattributes','AGENTS.md','CLAUDE.md','README.md','pyproject.toml','requirements.txt','gtm.ps1'}
ALLOWED_FOLDERS={'.claude','docs','examples','scripts','tests'}

def git(*args):
    return subprocess.check_output(['git','-c','safe.directory='+ROOT.as_posix(),'-c','core.quotepath=false',*args],cwd=ROOT)

def main():
    names=git('diff','--cached','--name-only','--diff-filter=ACMR','-z').decode().split('\0')
    forbidden=[]
    journal=ROOT/'local'/'GTM_Design_Partners_Etat.json'
    if journal.exists():
        state=json.loads(journal.read_text(encoding='utf-8-sig'))
        forbidden += [state['preferred_sender'], state['signature'], state.get('phone','')]
        for record in state['sent']:
            forbidden += [record['to'],record['result']['id'],record['result']['thread_id']]
    problems=[]
    for name in filter(None,names):
        parts=Path(name).parts
        if not (name in ALLOWED_ROOT or (len(parts)>1 and parts[0] in ALLOWED_FOLDERS)):
            problems.append(name+': not allowlisted')
            continue
        if Path(name).suffix.lower() in {'.xlsx','.csv','.zip','.png','.pem','.key'}:
            problems.append(name+': private/binary file type')
            continue
        text=git('show',':'+name).decode('utf-8')
        if any(value and value in text for value in forbidden):
            problems.append(name+': private campaign value found')
        if re.search(r'-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----|(?:ghp_|gho_|sk-proj-)[A-Za-z0-9]{20,}|auth_token=[A-Za-z0-9_-]{20,}',text):
            problems.append(name+': possible secret found')
    if problems:
        print('\n'.join(problems),file=sys.stderr)
        return 1
    print('Staged files checked: code, generic documentation, and synthetic examples only.')
    return 0

if __name__=='__main__':
    sys.exit(main())
