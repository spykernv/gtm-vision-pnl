"""Generate a dated view from the journal and optionally observed scheduler config."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tomllib

sys.dont_write_bytecode = True
from gtm import ROOT, Store, read


def build(root, automation_config=None):
    store = Store(root)
    state = read(store.path)
    status = store.status()
    scheduler = tomllib.loads(Path(automation_config).read_text(encoding='utf-8-sig')) if automation_config else {}
    rt = state['local_runtime']
    enabled = status['mode'] == 'live' and not status['emergency_stop'] and not status['activation_blockers']
    reply = 'Réponses encadrées autorisées' if enabled else 'Réponses automatiques suspendues'
    schedule = scheduler.get('status', 'NON VÉRIFIÉ')
    date = datetime.now(timezone.utc).isoformat()
    current = [s for s in state['sent'] if s.get('actual_from') == state['preferred_sender']]
    eligible = [s for s in current if s.get('conversation_state') not in {'STOPPED', 'BOUNCED', 'HANDOFF', 'BOOKED'}]
    old = len(state['sent']) - len(current)
    cutover = rt['gates'].get('old_automation_cutover', False)
    legacy = rt['gates'].get('legacy_coverage_resolved', False)
    first_reply = any(e.get('sent_id') for e in rt['events'].values())
    patches = {
        'Reprise': {
            'B4': f'Vue datée {date[:16]} UTC ; révision {rt["revision"]}. JSON = référence.',
            'B5': f'{state["preferred_sender"]} — signature avec téléphone obligatoire.',
            'B8': 'Ouvrir le dossier local, lire AGENTS.md puis le journal JSON. Excel est une vue dérivée.',
            'B11': f'{reply}. Aucune nouvelle vague ni relance froide.',
            'B12': f'{old} fils historiques : suivi manuel, hors lecture et réponse automatisées.' if legacy else 'Couverture historique à clarifier.',
            'B13': f'Tâche horaire : {schedule}. Bascule documentée : {"oui" if cutover else "non"}.'},
        'Reponses': {
            'A5': 'AUTORISATION ACTUELLE',
            'B4': f'Mode local : {status["mode"]}. Dernier scan : {status["last_completed_scan"] or "aucun"}.',
            'B5': f'{reply}. Prérequis manquants : {len(status["activation_blockers"])}.',
            'B18': f'Planification : {schedule}. PC, application et Internet nécessaires.',
            'B20': 'JSON = référence ; Excel = instantané daté. Historique privé hors Git.'},
        'Vague_1': {
            'B21': f'Lien sélectionné (à revérifier avant proposition) : {state["calendly"]["selected_event_url"]}',
            'B23': f'{len(state["sent"])} envois conservés ; {len(eligible)} fils admissibles. {old} historiques : {"hors autonomie" if legacy else "à clarifier"}.'}}
    markdown = f'''# État courant GTM Vision PnL

Instantané du {date} — journal révision {rt['revision']}.

| Contrôle | État observé |
|---|---|
| Moteur | {status['mode']} |
| Réponses | {reply} |
| Arrêt d’urgence | {status['emergency_stop']} |
| Tâche Desktop | {schedule} |
| Prérequis manquants | {', '.join(status['activation_blockers']) or 'Aucun'} |
| Dernière détection complète | {status['last_completed_scan']} |
| Fils admissibles du compte actuel | {len(eligible)} |
| Envois incertains | {len(status['uncertain_sends'])} |
| Notifications en attente | {status['pending_notifications']} |
| Première réponse avec reçu confirmé | {'Oui' if first_reply else 'Pas encore'} |

Le statut Desktop provient du fichier de configuration fourni, ou reste non vérifié.
La pause de l’ancienne tâche est attestée par l’utilisateur, sans relecture distante indépendante.
Les preuves initiales restent dans DELIVERY.md et les fichiers datés de local/evidence.
Les originaux et les messages déjà envoyés sont conservés. Les fils historiques sont hors autonomie.
Les sauvegardes locales protègent des erreurs de manipulation, pas de la perte du disque.
Ce document ne constitue ni un test Gmail ni un nouveau test du réveil planifié.
'''
    return {'generated_at': date, 'revision': rt['revision'], 'status': status,
            'scheduler': schedule, 'patches': patches, 'markdown': markdown}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--automation-config', type=Path)
    p.add_argument('--output', type=Path, help='Explicit Markdown destination; otherwise stdout only')
    args = p.parse_args()
    result = build(args.root, args.automation_config)
    if args.output:
        args.output.write_text(result['markdown'], encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
