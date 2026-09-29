# Apparence des emails — Vision P&L Correspondance

Créé le 28 septembre 2026 à la demande de Jonathan, à partir de deux captures d'un même email de référence externe, conservées hors Git. Le texte métier reste personnalisé ; seule sa présentation est standardisée. Ne pas reprendre la marque, le logo, les illustrations ou les promesses de cette référence. Les surlignages jaunes dans les captures ne sont pas repris.

## Référence réutilisable

- Source canonique : `examples/email-editorial-v1.html`.
- Génération : `python -X utf8 scripts/render_email.py local/inbox/email-design.json --output-dir local/email-preview`.
- Modèle actif validé le 28/09/2026 : photo restaurant et P.-S. approuvé. La commande charge automatiquement les trois champs de `local/email-design/active-style.json` ; le texte métier reste à personnaliser.
- L'aperçu privé et les captures de référence restent dans `local/`, jamais dans Git.
- Refonte du 28/09/2026 : direction correspondance professionnelle, papeterie ivoire et vert profond. Le chemin canonique est conservé pour les réutilisations.
- Couleurs : fond pierre #eceae4, papier #fdfcf8, vert #29463d, sauge #f1f2eb, filet olive #9a9e84, texte #4b534c.
- Titres Georgia ; corps Arial, 15 px / interligne 1,85 ; largeur maximale 664 px ; une colonne ; marges adaptées sous 600 px.
- Feuille délimitée sans ombre ; filet vert de 3 px ; en-tête discret ; titre mesuré ; lettre personnelle ; bloc pilote sauge à filet latéral ; bouton vert ; signature Arial et arrêt possible hors du papier.
- Toujours « Vision P&L », sans point décoratif après le logo ou le nom dans l'objet. Écrire « 8 à 12 semaines ». La signature conserve son texte exact, avec des chiffres de téléphone alignés en Arial. Une règle de style cible aussi les liens automatiques de la zone signature ; son application dépend du client email.
- Rôle validé par Jonathan le 28/09/2026 : « CEO vision P&L », en Arial 12 px sous ses coordonnées, remplace l'ancienne ligne « VISION P&L » seule. La casse reprend son libellé demandé ; le nom et le téléphone restent inchangés dans le bloc de signature exact. Les aperçus et reçus des tests déjà envoyés restent historiques ; l'aperçu courant se trouve dans `local/email-design/active-preview/`.
- Aucun fichier image distant, police externe, script ou pixel de suivi. Les portraits et logos optionnels sont joints au message en images incorporées CID.
- En-tête co-marqué depuis le 29/09/2026 : « Vision P&L × Marque », logo de la boutique à droite quand il a pu être récupéré (voir plus bas).

## Photos de signature et P.-S.

Les deux portraits fournis le 28/09/2026 sont conservés sans modification dans `local/email-design/assets/`, hors Git. Affichage carré de 88 px à gauche de l'identité, sans hébergement public. Les champs optionnels `portrait_path` (chemin relatif au moteur, obligatoirement sous ce dossier assets) et `portrait_alt` choisissent la photo. Sans photo, aucun emplacement vide. L'identité et les coordonnées restent lisibles indépendamment du chargement de l'image. Conserver la signature exacte et ne pas inventer de titre professionnel, distinction, sceau, certification ou preuve sociale.

Le champ `postscript` est affiché après la signature. Jonathan a retenu la version restaurant après les tests : le modèle actif associe cette photo au P.-S. approuvé. Son texte exact et le chemin de la photo se trouvent uniquement dans `local/email-design/active-style.json`, hors Git ; les reprendre de ce fichier, sans les reformuler. Ces champs sont appliqués par défaut aux nouveaux mails GTM. L'exemple testé reste dans `local/email-design/restaurant/input.json` ; ne pas en reprendre l'objet [TEST] pour un prospect.

## Co-marquage et logo de la boutique

Demande de Jonathan du 29/09/2026. L'en-tête affiche toujours « Vision *P&L* × Marque », avec le champ obligatoire `brand_name` : le nom commercial exact de la boutique, tel qu'il apparaît sur son site. « Vision P&L » et « × Marque » ne se coupent jamais entre eux.

Pendant la préparation de chaque mail, récupérer le logo de la boutique :

```text
python -X utf8 scripts/brand_logo.py https://boutique.example --brand "Marque"
```

Le script lit uniquement la page d'accueil publique et l'image qu'elle désigne : d'abord le logo de l'en-tête du site (thèmes Shopify et balisage courant), puis le logo JSON-LD, puis une apple-touch-icon d'au moins 120 px. Il écarte les bannières cookies, badges de paiement et variantes blanches ou « transparent », refuse un SVG (non affiché par Gmail), un logo trop petit, trop étiré ou trop clair pour le papier ivoire, puis détoure et produit un PNG à deux fois sa taille d'affichage (hauteur 36 px, largeur 180 px au plus). Résultat hors Git : `local/email-design/logos/<domaine>/logo.png` et `logo.json` (source, date, empreintes, candidats refusés et motif).

Si `logo.json` indique `"status": "logo"`, ajouter `brand_logo_path` au message : le logo remplace la mention « MARGE & COÛTS LOGISTIQUES » à droite de l'en-tête et part en image incorporée CID, comme la photo. Sinon, ne rien ajouter : la mention texte reste, sans emplacement vide. Regarder le logo avant envoi ; en cas de doute (mauvaise marque, image illisible), l'omettre. Sur mobile, le logo passe sous le nom. Un logo reste la marque du prospect : ne jamais le modifier au-delà du recadrage et du redimensionnement, ni l'utiliser ailleurs que dans le mail qui lui est adressé.

Premier test le 29/09/2026 sur une boutique Shopify de la liste : logo d'en-tête retenu, variante blanche écartée ; envoyé uniquement à une adresse de Jonathan, sans journal de campagne.

La variante professionnelle sans P.-S. est archivée dans `local/email-design/archive/2026-09-28-professional/`, avec ses fichiers préparés et ses captures. Sa photo source reste à son chemin d'origine pour préserver les aperçus historiques. `local/email-design/archived-variants.json` documente le déplacement ; les intentions et reçus des quatre tests envoyés sont conservés sans modification. Ne plus utiliser cette variante sans nouvelle instruction.

## Réutilisation

Pour les prochains nouveaux mails GTM, reprendre ce HTML plutôt que réinventer la mise en page. Pour une réponse courte dans un fil existant, garder la lisibilité de l'échange et la signature ; ne pas répéter automatiquement toute la carte de prospection. L'envoi des réponses reste manuel selon les consignes actuelles. La demande de template ne constitue aucune autorisation d'envoi.

Champs texte obligatoires : subject, preheader, eyebrow, headline, brand_name, salutation, observation, question, pilot_title, pilot_body, invitation, cta_label, cta_url, closing, signature, optout. Champ facultatif : brand_logo_path. Les valeurs sont échappées : ne pas fournir de HTML dans les champs. Un saut de ligne dans headline crée une coupure. Conserver la signature exacte du journal. Le pré-en-tête est visible dans la liste des messages, masqué dans le corps.

La commande de génération fusionne le style actif avec les champs du message. Les fonctions Python `render` et `build_payload` restent explicites : pour un appel direct, passer le même résultat de `apply_active_style(data)` aux deux. Une valeur explicitement présente dans le message est prioritaire ; ne modifier ces champs de style que sur nouvelle consigne de Jonathan. Les réponses courtes gardent la forme légère décrite ci-dessus.

Personnaliser le nom, l'entreprise et l'observation avec des faits sourcés. Ne pas ajouter d'allégation simplement pour remplir un champ. Ne pas reprendre les données de l'aperçu comme preuves pour un envoi futur. Le titre reste descriptif, le pilote exploratoire et les promesses inchangées. Pour une invitation à échanger, le bouton « Choisir un créneau » mène au Calendly sélectionné dans le journal et revalidé par le connecteur. L'URL actuelle est fournie dans l'aperçu privé ; le 28/09/2026, l'événement actif « Vision P&L e-commerce » dure 30 minutes. Aligner le texte sur la durée réellement vérifiée à chaque utilisation. La réponse directe au mail reste proposée en texte secondaire.

## Branchement au protocole existant

Le générateur produit email.html, email.txt (secours manuel), preview.html (aperçu local avec chemins des photos) et mime-payload.json (contenu MIME pour Gmail) ; il n'envoie rien et ne modifie pas le journal. Ne jamais envoyer preview.html : ses chemins locaux ne sont destinés qu'à l'aperçu.

Le moteur actuel compare le corps exact et concatène les contenus textuels des parties MIME. Sans image, utiliser une partie text/html. Avec photo et/ou logo, utiliser multipart/related : une seule partie text/html, puis une image binaire par visuel (photo, logo), chacune avec disposition inline et un Content-ID `portrait-…` ou `logo-…` correspondant à son src cid dans l'HTML. L'envoi passe par `scripts/gmail_smtp.py` (voir RUNBOOK) : le connecteur Gmail de Claude Code retire les images CID et les styles. campaign.body contient l'HTML exact ; la partie HTML du payload contient exactement le même HTML. La photo est encodée dans base64_url_content et ne doit pas être placée dans un champ textuel content. Ne pas joindre email.txt en multipart/alternative avec le comparateur actuel. La signature est conservée textuellement dans un bloc pre stylé. Si son échappement HTML modifie la signature exigée, arrêter avant l'envoi et adapter le protocole explicitement ; ne pas contourner sa validation.

Le moteur garde les contrôles de compte, doublons, autorisation, SENDING et reçu. Ne pas changer le HTML ou la photo entre armement et appel Gmail. Relire le message réel et valider le reçu, ainsi que la présence, le Content-ID et la taille de l'image incorporée ; une normalisation par Gmail peut empêcher la comparaison exacte, auquel cas l'envoi reste incertain et ne se réessaie pas. Les tests personnels de design explicitement demandés restent documentés sous local/email-design, sans créer de faux prospects dans le journal de campagne. Test navigateur ordinateur/mobile et test local de reçu ne prouvent pas le rendu en boîte réelle. Outlook, le mode sombre et les autres clients n'ont pas été vérifiés.

Documentation de référence : https://developers.google.com/workspace/gmail/design/css
