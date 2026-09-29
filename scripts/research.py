"""Contact research without a paid enrichment provider (fallback when Clay has no credits).

Every step writes JSON under local/research/ (never versioned) and prints a compact view,
so the agent reads one line per shop instead of raw pages:

  targets          journal rows without a named address (or without a decision-maker)
  crawl            each shop's own pages: published emails, people with a role, registry ids
  registry         official registries: legal representatives, headcount band, revenue
                   (FR recherche-entreprises.api.gouv.fr, BE KBO/BCE, CH Zefix + excerpt link)
  summarize        one line per shop from crawl + registry
  candidates       a person's usual address formats on the brand's mail domain
  verify           ask the mail server whether each mailbox exists: EHLO, MAIL FROM:<>,
                   RCPT TO, QUIT. No DATA command, so nothing is ever sent. A nonsense address
                   is probed first; a server that accepts it accepts everything, proves nothing.
  reviews          FR/CH/BE merchants reviewing a logistics app on the Shopify App Store
  probe            Shopify signal, currency and title for candidate domains of new brands
  draft-updates    record-update inputs from a short decisions file
  draft-additions  record-add inputs for new prospects
  simulate         replay the drafted inputs on a copy of the journal

An address may enter the journal only if its owner published it, or if `verify` marks it
`valide` (accepted on a domain that refuses unknown mailboxes). Everything else stays a
hypothesis. This module never writes the journal: gtm.py record-update and record-add do.
"""
import argparse
import concurrent.futures as cf
import html
import json
import re
import shutil
import smtplib
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unicodedata
from datetime import date
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/128 Safari/537.36',
      'Accept-Language': 'fr-FR,fr;q=0.9,en;q=0.8,de;q=0.7,nl;q=0.6'}
EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')
NOT_EMAIL = re.compile(r'\.(png|jpe?g|webp|gif|svg|css|js)$|sentry|wixpress|shopify|@2x|u003e|'
                       r'@(?:example|exemple|domain|email|mail)\.(?:com|org|net|fr)$', re.I)
GENERIC = re.compile(
    r'^(contact|contacto|contactus|kontakt|hello|hola|hallo|hi|info|support|sav|service|serviceclient|'
    r'service-client|service\.client|customer|customers|customerservice|customercare|care|wecare|help|web|'
    r'webmaster|commande|order|orders|bonjour|team|sales|welcome|admin|shop|onlineshop|store|boutique|'
    r'press|presse|pr|jobs|job|recrutement|careers|rh|hr|dpo|privacy|rgpd|gdpr|legal|compta|comptabilite|'
    r'facturation|billing|invoice|noreply|no-reply|newsletter|marketing|partenariat|partnership|b2b|pro|'
    r'wholesale|retail|office|mail|email|social)$', re.I)
ROLE = re.compile(r'(fondat(?:eur|rice)s?|co-?fondat(?:eur|rice)|founders?|co-?founder|ceo|coo|cfo|directeur|'
                  r'directrice|director|g[ée]rant(?:e)?|pr[ée]sident(?:e)?|responsable|head of|managing|'
                  r'gesch[äa]ftsf[üu]hr|inhaber|zaakvoerder|oprichter|bestuurder|administrat(?:eur|rice))', re.I)
IDS = {
    'siren': re.compile(r'(?:siren|rcs|r\.c\.s\.?|siret|immatricul\w*)[^0-9]{0,40}(\d{3}\s?\d{3}\s?\d{3})', re.I),
    'bce': re.compile(r'\b(?:BE\s?)?(0\d{3}[.\s]?\d{3}[.\s]?\d{3})\b'),
    'che': re.compile(r'CHE[-‐\s]?(\d{3}[.\s]?\d{3}[.\s]?\d{3})'),
}
KEEP_PATH = re.compile(r'/(pages|policies|blogs/[^/]+/[^/]+|a-propos|about|equipe|team|notre|qui|histoire|'
                       r'story|mentions|legal|impressum|contact|presse|press|fondat|founder)', re.I)
EXTRA = ['/pages/mentions-legales', '/policies/legal-notice', '/pages/legal-notice', '/pages/impressum',
         '/pages/a-propos', '/pages/about', '/pages/about-us', '/pages/notre-histoire', '/pages/qui-sommes-nous',
         '/pages/notre-equipe', '/pages/team', '/pages/contact', '/pages/presse', '/pages/press',
         '/policies/terms-of-service', '/policies/contact-information', '/']
TRANCHE = {'00': '0', '01': '1-2', '02': '3-5', '03': '6-9', '11': '10-19', '12': '20-49', '21': '50-99',
           '22': '100-199', '31': '200-249', '32': '250-499', '41': '500-999', 'NN': 'non employeur'}


def get(url, limit=700000):
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15,
                                   context=ssl.create_default_context())
        return r.geturl(), r.read(limit).decode('utf-8', 'replace')
    except Exception:
        return None, ''


def text_of(page):
    page = re.sub(r'(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>', ' ', page)
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', page)))


def is_generic(address):
    return bool(GENERIC.match(address.split('@')[0]))


# ---------- crawl ----------

def sitemap_urls(base):
    urls = []
    for loc in re.findall(r'<loc>([^<]+)</loc>', get(base + '/sitemap.xml')[1]):
        loc = html.unescape(loc)
        if not loc.endswith('.xml'):
            urls.append(loc)
        elif re.search(r'pages|policies|blogs|post|page', loc):
            urls += [html.unescape(u) for u in re.findall(r'<loc>([^<]+)</loc>', get(loc)[1])]
    return urls


def read_page(page, final, out):
    for m in re.findall(r'mailto:([^"\'?>\s]+)', page):
        m = html.unescape(m).strip().lower()
        if EMAIL.fullmatch(m) and not NOT_EMAIL.search(m):
            out['emails'].setdefault(m, final)
    body = text_of(page)
    for m in EMAIL.findall(body):
        m = m.lower().strip('.')
        if not NOT_EMAIL.search(m):
            out['emails'].setdefault(m, final)
    for key, rx in IDS.items():
        for m in rx.findall(body):
            out['ids'].setdefault(key, set()).add(re.sub(r'[\s.]', '', m))
    for m in ROLE.finditer(body):
        snippet = body[max(0, m.start() - 110): m.end() + 110].strip()
        if re.search(r'[A-ZÉÈ][a-zéèëïç]+[ -][A-ZÉÈ][A-Za-zéèëïç-]+', snippet) and len(out['people']) < 14:
            out['people'].append({'url': final, 'snippet': snippet})


def crawl_one(target):
    domain = target['domain']
    base = f'https://{domain}'
    pages = [u for u in sitemap_urls(base)
             if urlparse(u).netloc.replace('www.', '') == domain and KEEP_PATH.search(urlparse(u).path)]
    blogs = [u for u in pages if '/blogs/' in u][:25]
    todo = list(dict.fromkeys([base + p for p in EXTRA] + [u for u in pages if '/blogs/' not in u][:60] + blogs))
    out = {'rank': target['rank'], 'company': target['company'], 'domain': domain, 'pages_read': 0,
           'emails': {}, 'people': [], 'ids': {}}
    for url in todo:
        final, page = get(url)
        if page:
            out['pages_read'] += 1
            read_page(page, final, out)
    out['ids'] = {k: sorted(v) for k, v in out['ids'].items()}
    out['named_emails'] = {e: u for e, u in out['emails'].items() if not is_generic(e)}
    return out


# ---------- registry ----------

def fetch_json(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
    return json.loads(urllib.request.urlopen(req, timeout=25).read().decode('utf-8', 'replace'))


def fetch_text(url):
    _, page = get(url, 2_000_000)
    if page:
        return page
    # Some registries fail name resolution from Python on Windows while curl succeeds.
    return subprocess.run(['curl', '-sL', '-m', '25', '-A', UA['User-Agent'], url],
                          capture_output=True).stdout.decode('utf-8', 'replace')


def fr_search(query):
    time.sleep(0.25)
    url = 'https://recherche-entreprises.api.gouv.fr/search?per_page=3&q=' + urllib.parse.quote(query)
    return fetch_json(url).get('results', [])


def fr_summary(result, depth=0):
    people = []
    for x in result.get('dirigeants', []):
        if x.get('type_dirigeant') == 'personne physique':
            first = (x.get('prenoms') or '').split(' ')[0].title()
            people.append({'name': f"{first} {(x.get('nom') or '').title()}".strip(),
                           'role': x.get('qualite'), 'via': result.get('nom_complet')})
        elif depth == 0 and x.get('siren'):
            for holding in fr_search(x['siren'])[:1]:
                people += [dict(p, via=f"{x.get('denomination')} (holding)")
                           for p in fr_summary(holding, 1)['people']]
    finances = result.get('finances') or {}
    last = max(finances) if finances else None
    return {'legal_name': result.get('nom_complet'), 'siren': result.get('siren'),
            'created': result.get('date_creation'), 'active': result.get('etat_administratif'),
            'headcount': TRANCHE.get(result.get('tranche_effectif_salarie') or '', result.get('tranche_effectif_salarie')),
            'headcount_year': result.get('annee_tranche_effectif_salarie'),
            'revenue': {last: finances[last]} if last else None, 'people': people}


def kbo_people(page):
    flat = re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' | ', page)))
    block = flat.split('Fonctions', 1)[1].split('Qualités', 1)[0] if 'Fonctions' in flat else ''
    block = re.sub(r'(\|\s*)+', '| ', block)
    roles = r"(Administrateur délégué|Administrateur|Gérant|Représentant permanent|Personne déléguée à la gestion journalière|Fondateur d'une entité enregistrée personne physique)"
    people = []
    for role, name in re.findall(roles + r' \| ([^|0-9]+?, [^|0-9]+?) \|', block):
        last, first = [p.strip() for p in name.split(',', 1)]
        people.append({'name': f'{first} {last}'.strip(), 'role': role})
    return people


def be_summary(number):
    digits = re.sub(r'\D', '', number).zfill(10)
    time.sleep(0.5)
    page = fetch_text('https://kbopub.economie.fgov.be/kbopub/toonondernemingps.html'
                      f'?ondernemingsnummer={digits}&lang=fr')
    return {'bce': digits, 'people': kbo_people(page)}


def ch_summary(uid):
    digits = re.sub(r'\D', '', uid)
    formatted = f'CHE-{digits[:3]}.{digits[3:6]}.{digits[6:]}'
    time.sleep(0.5)
    firms = fetch_json('https://www.zefix.ch/ZefixREST/api/v1/firm/search.json',
                       data=json.dumps({'name': formatted, 'languageKey': 'fr', 'maxEntries': 3}).encode(),
                       headers={'Content-Type': 'application/json'}).get('list') or []
    if not firms:
        return {'uid': formatted}
    firm = fetch_json(f"https://www.zefix.ch/ZefixREST/api/v1/firm/{firms[0]['ehraid']}.json")
    # The people sit in the cantonal excerpt, which renders in a browser only.
    return {'uid': formatted, 'legal_name': firm.get('name'), 'excerpt': firm.get('cantonalExcerptWeb')}


def registry_one(crawled, override=None):
    ids, res = crawled.get('ids', {}), {}
    try:
        if override or ids.get('siren'):
            hits = fr_search(override or ids['siren'][0])
            if hits:
                res['fr'] = fr_summary(hits[0])
        if ids.get('bce'):
            res['be'] = [be_summary(n) for n in ids['bce'][:2]]
        if ids.get('che'):
            res['ch'] = ch_summary(ids['che'][0])
    except Exception as e:
        res['error'] = str(e)[:160]
    return res


# ---------- candidates ----------

def ascii_lower(text):
    text = text.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('Ä', 'ae').replace('Ö', 'oe').replace('Ü', 'ue')
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z\- ]', '', text)


def variants(full_name):
    """Usual mailbox spellings, most common first; German umlauts both folded and expanded."""
    out = []
    for name in dict.fromkeys([full_name, full_name.replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')]):
        parts = ascii_lower(name).split()
        if len(parts) < 2:
            out.append(parts[0]) if parts else None
            continue
        first, last, dashed = parts[0], ''.join(parts[1:]), '-'.join(parts[1:])
        flat_first = first.replace('-', '')
        initials = ''.join(p[0] for p in first.split('-'))
        out += [first, f'{first}.{last}', f'{initials}.{last}', f'{initials}{last}', f'{flat_first}{last}',
                f'{first}-{last}', f'{first}_{last}', last, f'{last}.{first}', f'{first}{last[0]}']
        if dashed != last:
            out.append(f'{first}.{dashed}')
        if flat_first != first:
            out.append(flat_first)
    return list(dict.fromkeys(out))


def candidates(people_file):
    """people_file: {"rank": {"domains": [...], "people": ["First Last", ...]}}"""
    spec = json.loads(Path(people_file).read_text(encoding='utf-8'))
    per_domain, owners = {}, {}
    for rank, entry in spec.items():
        for domain in entry['domains']:
            bucket = per_domain.setdefault(domain, [])
            for person in entry['people']:
                for local in variants(person):
                    address = f'{local}@{domain}'
                    if address not in bucket:
                        bucket.append(address)
                        owners[address] = [rank, person]
    return per_domain, owners


# ---------- verify ----------

def mx_hosts(domain):
    data = fetch_json(f'https://dns.google/resolve?name={domain}&type=MX')
    hosts = sorted((int(a['data'].split()[0]), a['data'].split()[1].rstrip('.'))
                   for a in data.get('Answer', []) if a.get('type') == 15)
    return [h for _, h in hosts] or [domain]


def helo_name():
    """Reverse DNS of the public address: some servers refuse a made-up HELO."""
    try:
        ip = urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode().strip()
        rev = '.'.join(reversed(ip.split('.'))) + '.in-addr.arpa'
        answer = fetch_json(f'https://dns.google/resolve?name={rev}&type=PTR').get('Answer') or []
        return answer[0]['data'].rstrip('.') if answer else 'localhost'
    except Exception:
        return 'localhost'


def verdict(session, address):
    code = session['results'].get(address, [0])[0]
    if code >= 500:
        return 'refusé'
    if code >= 400 or not code:
        return 'inconnu'
    return 'accepte-tout' if session['catch_all'] else 'valide'


def verify_domain(domain, addresses, owners, helo, per_session=10):
    res = {'domain': domain, 'mx': None, 'catch_all': None, 'results': {}, 'errors': []}
    try:
        hosts = mx_hosts(domain)
    except Exception as e:
        res['errors'].append(f'mx: {e}')
        return res
    done, queue = set(), list(addresses)
    while queue:
        batch = []
        for address in list(queue):
            queue.remove(address)
            if owners.get(address, [None, address])[1] not in done:
                batch.append(address)
            if len(batch) == per_session:
                break
        if not batch:
            break
        for host in hosts[:2]:
            try:
                smtp = smtplib.SMTP(host, 25, timeout=20)
                smtp.ehlo(helo)
                smtp.mail('<>')
                code, _ = smtp.rcpt(f'zq7x-nobody-{sum(map(ord, domain)) % 99991}@{domain}')
                res['catch_all'] = code < 300
                for address in batch:
                    if owners.get(address, [None, address])[1] in done:
                        continue
                    code, msg = smtp.rcpt(address)
                    res['results'][address] = [code, msg.decode('utf-8', 'replace')[:120]]
                    if code < 300:
                        done.add(owners.get(address, [None, address])[1])
                    time.sleep(0.4)
                smtp.quit()
                res['mx'] = host
                break
            except (smtplib.SMTPException, socket.error, OSError) as e:
                res['errors'].append(f'{host}: {str(e)[:140]}')
        time.sleep(1)
    res['verdicts'] = {a: verdict(res, a) for a in res['results']}
    return res


# ---------- journal-facing helpers (read the journal, never write it) ----------

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / 'local' / 'GTM_Design_Partners_Etat.json'
SET_ASIDE = re.compile(r'^À écarter', re.I)


def load_journal(path=JOURNAL):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def was_contacted(record, journal):
    return record.get('Statut') != 'À qualifier' or any(
        s.get('rank') == record['Rang'] or s.get('company') == record['Entreprise'] for s in journal['sent'])


def domain_of(url):
    if not (url or '').startswith('http'):
        return ''
    return urlparse(url).netloc.lower().replace('www.', '').replace('checkout.', '')


def targets_of(journal):
    """Rows worth researching: no named address to write to, or no decision-maker behind a shared inbox."""
    historical = {s['company'] for s in journal['sent'] if s.get('actual_from') != journal.get('preferred_sender')}
    out = []
    for r in journal['records']:
        if 'test interne' in r['Entreprise'].lower() or r['Entreprise'] in historical:
            continue
        if SET_ASIDE.match(r.get('À vérifier') or ''):
            continue
        contacted = was_contacted(r, journal)
        written = r.get('Email professionnel') or ''
        if contacted and (r.get('Email décideur') or (written and not is_generic(written))):
            continue
        if not contacted and written and not is_generic(written):
            continue
        domain = domain_of(r.get('Site / preuve Shopify'))
        if domain:
            out.append({'rank': r['Rang'], 'company': r['Entreprise'], 'country': r.get('Pays'),
                        'domain': domain, 'contacted': contacted,
                        'person': r.get('Décideur') if contacted else r.get('Contact public'),
                        'fallback': written or None})
    return out


def summary_line(crawled, reg):
    """One compact line per shop: what an agent needs to decide who to look for."""
    people, facts = [], []
    fr = reg.get('fr') or {}
    for p in fr.get('people', []):
        people.append(f"{p['name']} ({p.get('role') or '?'}{', via ' + p['via'] if 'holding' in (p.get('via') or '') else ''})")
    for be in reg.get('be') or []:
        people += [f"{p['name']} ({p['role']})" for p in be.get('people', [])]
    if fr:
        facts.append(f"{fr.get('legal_name')} {fr.get('siren')}, créée {fr.get('created')}, effectif {fr.get('headcount')}"
                     f"{' (' + fr['headcount_year'] + ')' if fr.get('headcount_year') else ''}"
                     f"{', CESSÉE' if fr.get('active') == 'C' else ''}")
        if fr.get('revenue'):
            year, fin = next(iter(fr['revenue'].items()))
            if fin.get('ca'):
                facts.append(f"CA {year} {fin['ca'] / 1e6:.1f} M€")
    if (reg.get('ch') or {}).get('excerpt'):
        facts.append(f"extrait CH à lire : {reg['ch']['excerpt']}")
    named = list(crawled.get('named_emails', {}))[:3]
    generic = [e for e in crawled.get('emails', {}) if e not in crawled.get('named_emails', {})][:3]
    return (f"{crawled['rank']} {crawled['company']} [{crawled['domain']}] pages={crawled['pages_read']} | "
            f"personnes: {'; '.join(people[:4]) or '—'} | {' ; '.join(facts) or 'registre: —'} | "
            f"nominatifs: {', '.join(named) or '—'} | génériques: {', '.join(generic) or '—'}"
            f"{' | erreur: ' + reg['error'] if reg.get('error') else ''}")


def verified_addresses(verify_files):
    ok = set()
    for f in verify_files or []:
        for r in json.loads(Path(f).read_text(encoding='utf-8')).values():
            ok |= {a for a, v in r.get('verdicts', {}).items() if v == 'valide'}
    return ok


PROOF = {
    'smtp': 'SMTP {day} : acceptée, domaine qui refuse les adresses inconnues',
    'published': 'publiée par la personne',
    'fallback': 'repli boutique : adresse nominative non vérifiable',
    'none': 'aucune adresse nominative vérifiée',
}


def draft_updates(decisions, journal, authorization, outdir, verify_files=None, day=None):
    """decisions: [{"rank", "person", "email"?, "proof": smtp|published|fallback|none, "source", "checks"?}]"""
    day = day or date.today().strftime('%d/%m/%Y')
    records = {r['Rang']: r for r in journal['records']}
    checked = verified_addresses(verify_files)
    Path(outdir).mkdir(parents=True, exist_ok=True)
    written = []
    for d in decisions:
        r = records[d['rank']]
        proof, email = d.get('proof', 'none'), d.get('email')
        if proof == 'smtp' and verify_files and email not in checked:
            raise ValueError(f"{email} n'est pas « valide » dans les résultats SMTP fournis")
        provenance = f"{d['source']} ; {PROOF[proof].format(day=day)} • {day}"
        if was_contacted(r, journal):
            fields = {'Décideur': d['person'], 'Décideur : provenance': provenance}
            if email and proof in ('smtp', 'published'):
                fields['Email décideur'] = email
            name = f"dm-{r['Rang']:03d}.json"
        else:
            fields = {'Contact public': d['person'], 'Email : provenance': provenance}
            if email:
                fields['Email professionnel'] = email
            if d.get('checks'):
                previous = r.get('À vérifier') or ''
                fields['À vérifier'] = d['checks'] if d['checks'] in previous else f"{d['checks']} ; {previous}".strip(' ;')
            name = f"nc-{r['Rang']:03d}.json"
        item = {'authorization': authorization, 'rank': r['Rang'], 'company': r['Entreprise'], 'fields': fields,
                'evidence': {'method': 'docs/RESEARCH.md', 'sources': d['source'], 'proof': proof, 'checked_at': day}}
        (Path(outdir) / name).write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding='utf-8')
        written.append(name)
    return written


def draft_additions(prospects, journal, authorization, outdir, day=None):
    """prospects: [{"company", "country", "site", "shop", "logistician", "proof3pl", "source",
    "contact"?, "email"?, "profile"?, "provenance", "angle", "checks"}]"""
    day = day or date.today().strftime('%d/%m/%Y')
    taken = {r['Entreprise'].strip().lower() for r in journal['records']}
    rank = max(r['Rang'] for r in journal['records'])
    Path(outdir).mkdir(parents=True, exist_ok=True)
    written = []
    for p in prospects:
        if p['company'].strip().lower() in taken:
            raise ValueError(f"{p['company']} est déjà dans le journal")
        taken.add(p['company'].strip().lower())
        rank += 1
        record = {'Rang': rank, 'Sélection': 'Réserve', 'Entreprise': p['company'], 'Pays': p['country'],
                  'Shopify': 'Confirmé — signal technique', 'Logisticien / indice': p.get('logistician') or 'Non établi',
                  'Preuve 3PL': p.get('proof3pl') or 'Non établi', 'Angle à tester': p.get('angle'),
                  'À vérifier': p.get('checks'), 'Contact public': p.get('contact'),
                  'Email professionnel': p.get('email'), 'Profil du contact': p.get('profile'),
                  'Source logistique / origine': p.get('source') or p['site'], 'Site / preuve Shopify': p['site'],
                  'Signal Shopify observé': f'Shopify.shop = "{p["shop"]}" ({day})',
                  'Email : provenance': f"{p['provenance']} • {day}"}
        item = {'authorization': authorization, 'record': record,
                'evidence': {'origin': p.get('source') or 'sélection manuelle', 'shopify_signal': p['shop'],
                             'method': 'docs/RESEARCH.md', 'checked_at': day}}
        name = f'add-{rank:03d}.json'
        (Path(outdir) / name).write_text(json.dumps(item, ensure_ascii=False, indent=1), encoding='utf-8')
        written.append(name)
    return written


def simulate(indir, journal_path=JOURNAL):
    """Replay drafted inputs on a throwaway copy of the journal; the real one is untouched."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / 'local').mkdir()
        shutil.copy2(journal_path, Path(tmp) / 'local' / Path(journal_path).name)
        results = {}
        for f in sorted(Path(indir).glob('*.json')):
            cmd = 'record-add' if f.name.startswith('add-') else 'record-update'
            run = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts' / 'gtm.py'), '--root', tmp, cmd, str(f)],
                                 capture_output=True, text=True, encoding='utf-8')
            results[f.name] = 'ok' if run.returncode == 0 else (run.stderr.strip() or run.stdout.strip())[:200]
        return results


# ---------- new prospects ----------

def app_reviews(app, pages=20):
    """FR/CH/BE merchants who reviewed a Shopify app: a store name, a country, a date."""
    def one(n):
        _, page = get(f'https://apps.shopify.com/{app}/reviews?locale=fr&page={n}', 400000)
        rows = []
        for block in page.split('data-merchant-review=""')[1:]:
            flat = re.sub(r'(\|\s*)+', '| ', re.sub(r'\s+', ' ', html.unescape(
                re.sub(r'<[^>]+>', ' | ', re.sub(r'<path[^>]*>', '', block[:12000])))))
            fields = [x.strip() for x in flat.split('|') if x.strip()]
            at = next((i for i, x in enumerate(fields) if "utilisation de l" in x), None)
            if at and at >= 2:
                rows.append({'store': fields[at - 2], 'country': fields[at - 1], 'date': fields[1][:40]})
        return rows
    with cf.ThreadPoolExecutor(8) as pool:
        rows = [r for batch in pool.map(one, range(1, pages + 1)) for r in batch]
    keep = [r for r in rows if r['country'] in ('France', 'Suisse', 'Belgique')]
    return {'app': app, 'reviews': len(rows), 'merchants': keep}


def probe_domain(domain):
    for prefix in ('https://www.', 'https://'):
        final, page = get(prefix + domain, 600000)
        if page:
            shop = re.search(r'Shopify\.shop\s*=\s*"([^"]+)"', page)
            currency = re.search(r'Shopify\.currency\s*=\s*\{"active":"([A-Z]{3})"', page)
            title = re.search(r'<title[^>]*>([^<]{0,90})', page, re.I)
            return {'domain': domain, 'url': final.split('?')[0], 'shop': shop.group(1) if shop else None,
                    'currency': currency.group(1) if currency else None,
                    'title': html.unescape(title.group(1).strip()) if title else ''}
    return {'domain': domain, 'url': None, 'shop': None}


def probe(candidates_list):
    """candidates_list: [[brand, source, [domain guesses...]]] -> first guess with a Shopify signal."""
    jobs = [(brand, source, d) for brand, source, guesses in candidates_list for d in guesses]
    with cf.ThreadPoolExecutor(12) as pool:
        hits = list(pool.map(lambda j: (j[0], j[1], probe_domain(j[2])), jobs))
    out = {}
    for brand, source, hit in hits:
        best = out.setdefault(brand, {'source': source, 'hit': None})
        if hit.get('shop') and not (best['hit'] or {}).get('shop'):
            best['hit'] = hit
        elif not best['hit'] and hit.get('url'):
            best['hit'] = hit
    return out


# ---------- cli ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('targets'); p.add_argument('out')
    p = sub.add_parser('crawl'); p.add_argument('targets'); p.add_argument('out')
    p = sub.add_parser('registry'); p.add_argument('crawl'); p.add_argument('out')
    p.add_argument('--names', help='{"rank": "legal name or SIREN"} when the site shows none')
    p = sub.add_parser('summarize'); p.add_argument('crawl'); p.add_argument('registry'); p.add_argument('out')
    p = sub.add_parser('candidates'); p.add_argument('people'); p.add_argument('out')
    p = sub.add_parser('verify'); p.add_argument('candidates'); p.add_argument('out')
    p = sub.add_parser('reviews'); p.add_argument('app'); p.add_argument('out'); p.add_argument('--pages', type=int, default=20)
    p = sub.add_parser('probe'); p.add_argument('candidates'); p.add_argument('out')
    for name in ('draft-updates', 'draft-additions'):
        p = sub.add_parser(name); p.add_argument('decisions'); p.add_argument('outdir')
        p.add_argument('--authorization', required=True, help='the instruction quoted from the chat')
        p.add_argument('--verify', nargs='*', help='verify.json files that must contain every smtp-proof address')
    p = sub.add_parser('simulate'); p.add_argument('indir')
    args = parser.parse_args()
    if args.cmd in ('draft-updates', 'draft-additions', 'simulate'):
        if args.cmd == 'simulate':
            result = simulate(args.indir)
            bad = {k: v for k, v in result.items() if v != 'ok'}
            print(f"simulate: {len(result) - len(bad)} ok, {len(bad)} refusés")
            for k, v in bad.items():
                print(f'  {k}: {v}')
            return 2 if bad else 0
        decisions = json.loads(Path(args.decisions).read_text(encoding='utf-8'))
        if args.cmd == 'draft-updates':
            names = draft_updates(decisions, load_journal(), args.authorization, args.outdir, args.verify)
        else:
            names = draft_additions(decisions, load_journal(), args.authorization, args.outdir)
        print(f'{args.cmd}: {len(names)} fichiers dans {args.outdir}')
        return 0
    if args.cmd == 'targets':
        result = targets_of(load_journal())
        for t in result:
            print(f"{t['rank']} {t['company']} [{t['domain']}] {'contactée' if t['contacted'] else 'à contacter'} | "
                  f"{(t['person'] or '—')[:60]} | {t['fallback'] or '—'}")
    elif args.cmd == 'summarize':
        crawled = json.loads(Path(args.crawl).read_text(encoding='utf-8'))
        reg = json.loads(Path(args.registry).read_text(encoding='utf-8'))
        result = [summary_line(c, reg.get(str(c['rank'])) or {}) for c in crawled]
        print('\n'.join(result))
    elif args.cmd == 'reviews':
        result = app_reviews(args.app, args.pages)
        print(f"{args.app}: {result['reviews']} avis, {len(result['merchants'])} FR/CH/BE")
        for m in result['merchants']:
            print(f"  {m['store']} | {m['country']} | {m['date']}")
    elif args.cmd == 'probe':
        result = probe(json.loads(Path(args.candidates).read_text(encoding='utf-8')))
        for brand, v in result.items():
            h = v['hit'] or {}
            print(f"{'SHOP' if h.get('shop') else '----'} {brand} | {h.get('url')} | {h.get('shop')} | {h.get('currency')} | {h.get('title', '')[:60]}")
    elif args.cmd == 'crawl':
        targets = json.loads(Path(args.targets).read_text(encoding='utf-8'))
        with cf.ThreadPoolExecutor(10) as pool:
            result = list(pool.map(crawl_one, targets))
    elif args.cmd == 'registry':
        names = json.loads(Path(args.names).read_text(encoding='utf-8')) if args.names else {}
        result = {c['rank']: registry_one(c, names.get(str(c['rank'])))
                  for c in json.loads(Path(args.crawl).read_text(encoding='utf-8'))}
    elif args.cmd == 'candidates':
        per_domain, owners = candidates(args.people)
        result = {'candidates': per_domain, 'owners': owners}
    else:
        spec = json.loads(Path(args.candidates).read_text(encoding='utf-8'))
        helo = helo_name()
        result = {d: verify_domain(d, a, spec['owners'], helo) for d, a in spec['candidates'].items()}
        for d, r in result.items():
            found = [a for a, v in r['verdicts'].items() if v == 'valide']
            print(d, '| accepte-tout' if r['catch_all'] else '', '|', ', '.join(found) or '—')
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=1, default=sorted), encoding='utf-8')
    print(f'{args.cmd}: {len(result)} entrées écrites dans {args.out}')


if __name__ == '__main__':
    sys.exit(main())
