# MediConnect : module « Gestion patient » avec triage intelligent

Application web de gestion des patients et de leurs rendez-vous médicaux. Le patient décrit ce qu'il ressent, le site évalue
l'urgence, l'oriente vers la bonne spécialité, lui donne une heure de rendez-vous (fixée ou estimée) et le prévient par
e-mail quand elle change. Le médecin garde toujours la décision finale.

**Technologies** : Python 3.12/3.13, Django 5.2, MongoDB Atlas (`django-mongodb-backend`), scikit-learn, Celery + Redis,
Tailwind CSS. Déploiement : Docker, Railway (site, worker, Redis) et Vercel (porte d'entrée publique).

> Ce dépôt réunit les modules de l'équipe : patients et back-office (Ismail), médecins avec consultations, visio et compte
> rendu PDF, e-mail ou WhatsApp (Mourad), infirmiers et soins à domicile (Walid), pharmacies et ordonnances (Ahmed). Le module
> laboratoires n'a pas été réalisé (équipe de quatre). Les médecins proposés aux patients sont ceux du module médecins
> (`medecins/annuaire.py`).

---

## Sommaire

1. [Ce que fait le site](#1-ce-que-fait-le-site)
2. [Le triage : quel niveau d'urgence ?](#2-le-triage--quel-niveau-durgence-)
3. [Les modèles d'intelligence artificielle](#3-les-modèles-dintelligence-artificielle)
4. [La file d'attente équitable et l'agenda prévisionnel](#4-la-file-dattente-équitable-et-lagenda-prévisionnel)
5. [Les e-mails](#5-les-e-mails)
6. [Le back-office administrateur](#6-le-back-office-administrateur)
7. [Accessibilité et sécurité](#7-accessibilité-et-sécurité)
8. [Qualité : tests et vérifications](#8-qualité--tests-et-vérifications)
9. [Structure du projet](#9-structure-du-projet)
10. [Installer et lancer](#10-installer-et-lancer)
11. [Déploiement](#11-déploiement)
12. [Commandes utiles](#12-commandes-utiles)
13. [Documents d'explication](#13-documents-dexplication)
14. [Limites assumées](#14-limites-assumées)
15. [Branches Git](#15-branches-git)

---

## 1. Ce que fait le site

### Espace patient

| Fonction | Détail |
|---|---|
| **Inscription et connexion** | Création du compte, du profil patient et du dossier médical en une seule fois. Mot de passe oublié par e-mail (lien valable 2 h, sessions invalidées après le changement). |
| **Mon compte** | Identité, changement de mot de passe, **export de toutes mes données** (JSON), désactivation ou suppression du compte. |
| **Dossier médical** | Groupe sanguin, antécédents, traitements en cours. |
| **Allergies** | Ajout, modification, suppression, avec gravité (légère, modérée, sévère) et réaction. |
| **Mesures de santé** | Poids, tension, glycémie, température, pouls, saturation, avec repères normaux, courbes et export CSV. |
| **Quel médecin consulter ?** | Le patient décrit son ressenti : le site propose la **spécialité conseillée** et les **médecins disponibles**. Rien n'est enregistré. |
| **Demande de rendez-vous** | Choix du médecin, description des symptômes (cases, échelles de 0 à 5, texte libre), résultat du triage avec explication. |
| **Créneau ou file** | Niveaux 3 à 5 : choix d'un créneau fixe, ou « rester dans la file ». Niveaux 1 et 2 : prise en charge en priorité. |
| **Suivi de la demande** | Place, heure prévue, retard éventuel, annulation, changement de médecin proposé. |
| **Consultations** | Historique des compte rendus (diagnostic, prescription, recommandations). |
| **Analyse du dossier** | Alertes classées (allergie contre médicament, interactions, cohérence, mesures récentes) et synthèse en langage clair. |

### Parcours en 6 étapes

Créer mon espace, trouver mon médecin, décrire mes symptômes, mon tour (rendez-vous ou file), j'attends, consultation et après.
Le schéma complet est dans [`docs/Parcours_Patient_MediConnect.pdf`](docs/Parcours_Patient_MediConnect.pdf).

---

## 2. Le triage : quel niveau d'urgence ?

Le niveau va de **1 (vital)** à **5 (non urgent)**. Il est calculé par trois lecteurs qui se complètent :

1. **Règles pondérées** (`patients/triage.py`) : des points par symptôme, par constante (température, saturation…) et par échelle.
   20 points ou plus : niveau 2 ; 12 ou plus : niveau 3 ; 5 ou plus : niveau 4 ; sinon niveau 5. Un **signe d'alerte**
   (douleur thoracique, perte de connaissance, saignement abondant…) impose un niveau minimal.
2. **Modèle de lecture du texte** (apprentissage automatique, local) : lit le texte libre et estime un niveau.
3. **IA de langage facultative** : repère dans le texte des signes non cochés, avec leur citation exacte.

Règles de sécurité : le modèle et l'IA peuvent **relever** l'urgence, **jamais la baisser** ; ils ne décident jamais d'un cas
vital ; le médecin peut requalifier le niveau.

---

## 3. Les modèles d'intelligence artificielle

| | Outil | Nature | Reçoit | Produit |
|---|---|---|---|---|
| **A** | Orientation vers une spécialité | TF-IDF + régression logistique | Un texte libre | Une spécialité conseillée (9 choix) + les médecins disponibles |
| **B** | Triage par règles | Score à règles pondérées | Symptômes, constantes, échelles | Un niveau d'urgence de 1 à 5 |
| **C** | Lecture du texte du triage | TF-IDF + régression logistique | Le texte libre | Un niveau estimé + un degré de confiance |
| **D** | IA de langage (facultative) | Qwen via Groq, ou Qwen 2.5 en local avec Ollama | Le texte anonymisé, avec accord du patient | Des signes repérés avec citation |
| **E** | File et agenda | Algorithmes | Niveaux, ancienneté, rendez-vous, horaires | Place et heure prévue de chacun |
| **F** | Analyse du dossier | Règles (IA en option) | Allergies, traitements, mesures, consultations | Alertes classées + synthèse |

**Les deux modèles appris (A et C)** sont petits (environ 270 Ko et 430 Ko), tournent sur le serveur sans carte graphique et sont
**versionnés dans le dépôt** (`ia/artefacts/`). Ils sont entraînés sur des **phrases générées** à partir d'un lexique, sans aucune
donnée de vrais patients ; le niveau d'urgence de chaque phrase est calculé par les règles du projet.

Résultats mesurés (fichiers `ia/artefacts/evaluation*.json`) :

| Modèle | Test sur phrases générées | Test sur phrases écrites à la main |
|---|---|---|
| Lecture du texte (niveau exact) | 93 % (1 500 phrases) | 90 % (39 phrases) |
| dont cas graves repérés | 97 % | 92 % |
| Orientation (bonne spécialité) | 100 % (1 350 phrases, test facile) | **93 %** (30 phrases) |

Le test à la main est le plus honnête : il porte sur peu de phrases, l'ordre de grandeur est fiable, pas la décimale.

**Garde-fous** : confiance minimale (85 % pour relever un niveau, 70 % pour proposer une spécialité, sinon médecine générale) ;
mots décisifs affichés ; texte anonymisé avant tout envoi à l'IA externe, avec accord du patient ; citations de l'IA vérifiées ;
sans IA, tout fonctionne.

---

## 4. La file d'attente équitable et l'agenda prévisionnel

**File d'attente** (`patients/file_attente.py`) : un délai cible par niveau, en minutes de **présence du médecin**.

| Niveau | Délai visé | Passe en tête au plus tard (3 × le délai) |
|---|---|---|
| 1 Vital | immédiat | dès que le médecin est libre |
| 2 Très urgent | 30 min | 1 h 30 |
| 3 Urgent | 2 h | 6 h |
| 4 Standard | 8 h | 24 h |
| 5 Non urgent | 24 h | 72 h |

Personne n'attend sans fin : chaque fois qu'une demande plus récente passe devant, un **dépassement** est compté. Après **5
dépassements** la demande est **protégée** (seuls les niveaux 1 à 3 passent encore devant), et après 3 fois son délai elle passe
même devant les urgents, sauf le cas vital. Tous ces réglages sont modifiables par l'administrateur.

**Agenda prévisionnel** (`patients/agenda.py`) : une simulation de la journée de chaque médecin donne l'**heure prévue de
chacun**. Une urgence passe d'abord et décale les rendez-vous suivants ; un niveau 3 prend seulement les trous ; un rendez-vous
n'est jamais prévu avant son heure ; un trou dans l'agenda efface le retard. Patient et administrateur voient les mêmes heures.

---

## 5. Les e-mails

Envoyés en **texte et HTML** (gabarit commun), sans aucune donnée médicale, et une panne d'envoi ne bloque jamais le rendez-vous.

| E-mail | Quand |
|---|---|
| Rendez-vous confirmé / modifié | Le patient choisit ou change son créneau |
| Rendez-vous retardé / retrouve son heure | L'heure prévue change d'au moins **10 minutes** |
| Demande enregistrée (file) | Place et heure **estimée**, avec rappel « SAMU : 190 » |
| Heure estimée changée | Changement d'au moins **30 minutes** pour la file |
| Annulation | Rendez-vous ou demande annulés |
| Mot de passe oublié | Lien valable 2 h |

Sans réglage, les messages s'affichent dans la console du serveur. Pour un vrai envoi (Gmail avec un mot de passe d'application),
renseigner les variables `EMAIL_*` du `.env`.

---

## 6. Le back-office administrateur

Accessible sur `/backoffice/` aux comptes administrateur :

* **Tableau de bord** : chiffres clés, répartition des niveaux, demandes à surveiller.
* **Rendez-vous** : liste filtrable, détail d'une demande, requalification du niveau, changement de statut, **compte rendu de consultation**.
* **File d'attente** : pour chaque médecin, l'ordre de passage, les rendez-vous fixés et les heures prévues.
* **Patients** : recherche et filtres, export CSV protégé contre l'injection de formules, désactivation et réactivation.
* **Paramètres** : délais, plafond de dépassements, seuils et durée de consultation ; page du **modèle de lecture du texte** avec son évaluation.
* **Symptômes** : catalogue des symptômes du triage.

---

## 7. Accessibilité et sécurité

**Accessibilité (WCAG 2.1 AA)** : structure sémantique (un `main`, `nav` nommés, pied de page, titres cohérents), lien d'évitement,
focus visible, icônes décoratives masquées aux lecteurs d'écran, champs liés à leur aide et à leurs erreurs, `autocomplete`,
contrastes calculés à partir des CSS (minimum 6,3:1), information jamais portée par la couleur seule. La commande
`python manage.py audit_accessibilite` contrôle les pages ; **Lighthouse : 100/100 en accessibilité** sur les pages publiques et
connectées de chaque rôle (rapports dans `docs/lighthouse/`).

**Sécurité (bases OWASP)** :

| Exigence | Mise en œuvre |
|---|---|
| Contrôle d'accès par rôle | chaque espace vérifie le rôle ; la gestion des comptes exige les **permissions Django** (`LoginRequiredMixin` + `PermissionRequiredMixin`) portées par un **groupe par rôle** (`core/roles.py`, mis à jour à chaque `migrate`) ; une donnée d'un autre compte répond 404 |
| Force brute | 5 échecs pour un identifiant -> connexion suspendue 15 min, même avec le bon mot de passe (`core/securite.py`) |
| Traçabilité | **journal des connexions** (connexions, échecs, blocages, déconnexions, IP, navigateur ; jamais le mot de passe), consultable dans le back-office ; purge à 90 jours (`purger_journal`) |
| CSRF, injections | protection CSRF sur tous les formulaires (page claire si le jeton expire) ; uniquement l'ORM, aucune requête brute |
| Mots de passe | hachés (PBKDF2), validateurs Django, réinitialisation par lien à durée limitée |
| Production | `DJANGO_ENV=production` : refus de démarrer avec `DEBUG=True` ou une clé faible ; HTTPS forcé, HSTS, cookies `Secure`/`HttpOnly`, `X-Frame-Options: DENY`, `nosniff` ; `manage.py check --deploy` sans avertissement |
| Secrets | uniquement dans les variables d'environnement (`.env` local, Railway en ligne), jamais dans Git |
| Erreurs | pages 400, 403, 404 et 500 personnalisées ; services externes (IA, e-mail, SMS) toujours dans un `try/except` qui journalise sans bloquer |

---

## 8. Qualité : tests et vérifications

```bash
python manage.py test                       # MongoDB local requis pour les tests d'intégration (MONGODB_TEST_URI)
coverage run manage.py test && coverage report   # rapport de couverture (coverage html -> htmlcov/)
```

* **Tests unitaires** (`tests.py` de chaque app, sans base) : règles du triage et des alertes, modèles, garde-fous de l'IA
  avec une IA simulée, formulaires, gabarits, accessibilité.
* **Tests d'intégration** (`tests_integration.py`, vraie base de test + client HTTP de Django) : inscription, connexion et
  blocage, CRUD complet de chaque entité par les pages, **matrice des accès** (5 rôles × 21 adresses : anonyme -> connexion,
  autre rôle -> 403), gestion des comptes, CSRF, pages d'erreur, réglages de production.
* **Tâches de fond** (`tests_taches.py`) : Celery avec et sans Redis.
* **Intégration continue** : GitHub Actions (`.github/workflows/ci.yml`) relance tout, avec MongoDB et Redis, à chaque Pull
  Request, vérifie `check --deploy` et publie le rapport de couverture.

---

## 9. Structure du projet

```
mediconnect/             réglages Django, URL racine
core/                    comptes, connexion, mot de passe, e-mails de base, accessibilité
patients/                module patient
  triage.py                règles pondérées du triage
  file_attente.py          file équitable
  agenda.py                heures prévues (logique pure)
  suivi.py                 place, heure prévue, e-mails de changement
  planning.py              créneaux de rendez-vous
  notifications.py         e-mails au patient
  analyse_dossier.py       analyse du dossier par règles
  ia_*.py                  IA de langage facultative et ses garde-fous
  templates/patients/      pages et e-mails
ia/                      modèles d'apprentissage automatique
  modele.py, donnees.py, lexique.py          lecture du texte du triage
  specialite.py, lexique_specialite.py       orientation vers une spécialité
  artefacts/                                 modèles entraînés et évaluations (versionnés)
backoffice/              espace administrateur
templates/, static/      page d'accueil, styles
docs/                    PDF d'explication
```

---

## 10. Installer et lancer

Il faut **Python 3.13** (3.11 ou plus convient) et **Git**.

```bash
git clone https://github.com/smailch/Esprit-django--5TWIN1-2027-MediConnect.git
cd Esprit-django--5TWIN1-2027-MediConnect
git checkout preprod
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Linux/Mac : cp .env.example .env
```

Renseigner le fichier `.env` :

| Variable | Valeur |
|---|---|
| `MONGODB_URI` | adresse de connexion MongoDB Atlas (à demander à l'équipe, jamais dans Git) |
| `MONGODB_NAME` | nom de la base (`mediconnect`) |
| `DJANGO_SECRET_KEY` | une phrase longue au hasard |
| `DJANGO_DEBUG` | `True` en développement |

**Autoriser l'ordinateur sur Atlas** : projet MediConnect, *Network Access*, *Add Current IP Address*. Sans cela, le site affiche
« SSL handshake failed » à chaque accès à la base.

```bash
python manage.py migrate                  # inutile avec la base partagée déjà prête
python manage.py charger_symptomes        # catalogue de symptômes du triage
python manage.py charger_demo             # facultatif : patients de démonstration (identifiants préfixés demo_)
python manage.py runserver
```

Le site est sur http://127.0.0.1:8000/.

**Les modèles sont dans le dépôt** : rien à télécharger ni à entraîner. La version de `scikit-learn` est figée dans
`requirements.txt` ; si un modèle est illisible, il est réentraîné automatiquement en quelques secondes.

**Facultatif** : IA de langage (Groq gratuit), e-mails réels et Redis (tâches de fond), voir `.env.example`.

**Pour les tests d'intégration**, un MongoDB local suffit (`mongodb://localhost:27017`, ou `MONGODB_TEST_URI`) : les tests créent
puis suppriment leur propre base `test_mediconnect` et ne touchent jamais au cluster Atlas.

**Tout en conteneurs** (site, worker Celery, Redis, MongoDB) :

```bash
docker compose up --build                                   # http://localhost:8000
docker compose exec web python manage.py charger_demo       # données de démonstration dans le MongoDB du conteneur
```

---

## 11. Déploiement

```
Navigateur ─HTTPS─> Vercel (porte d'entrée, réécriture) ─HTTPS─> Railway « web » (gunicorn + Django + WhiteNoise)
                                                                   │                     │
                                                   Railway « Redis » <── Railway « worker » (Celery)
                                                                   │
                                                          MongoDB Atlas
```

| Fichier | Rôle |
|---|---|
| `Dockerfile` | une seule image : `SERVICE=web` (migrations puis gunicorn) ou `SERVICE=worker` (Celery) |
| `railway.json`, `deploiement/railway-worker.json` | services Railway web (sonde `/sante/`) et worker |
| `deploiement/vercel/` | projet Vercel qui renvoie toutes les requêtes vers Railway |
| `docker-compose.yml` | la même architecture sur un poste |
| `.github/workflows/ci.yml` | tests, `check --deploy` et couverture à chaque Pull Request |

Variables de production : `DJANGO_ENV=production`, `DJANGO_DEBUG=False`, `DJANGO_SECRET_KEY` (64 caractères aléatoires),
`DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS`, `MONGODB_URI`, `MONGODB_NAME`, `REDIS_URL`, puis l'IA et l'e-mail.

**Celery + Redis** : les e-mails de notification, l'analyse IA du dossier patient (deux appels à l'IA, jusqu'à 12 s) et la
relecture IA d'un compte rendu enregistré pendant une panne de l'IA partent en tâche de fond ; la page répond tout de suite
et affiche un indicateur, puis le résultat. Sans `REDIS_URL`, tout s'exécute dans la requête, comme avant.

---

## 12. Commandes utiles

| Commande | Rôle |
|---|---|
| `python manage.py test` | lancer tous les tests (MongoDB local pour les tests d'intégration) |
| `coverage run manage.py test && coverage report` | mesurer la couverture des tests |
| `python manage.py check --deploy` | vérifier les réglages de production (avec `DJANGO_ENV=production`) |
| `celery -A mediconnect worker -l info` | lancer le worker des tâches de fond (avec `REDIS_URL`) |
| `python manage.py evaluer_alertes` | mesurer la détection des alertes des soins (règles, puis règles + IA) |
| `python manage.py synchroniser_roles` | recréer les groupes et permissions des rôles |
| `python manage.py purger_journal --jours 90` | supprimer les vieilles entrées du journal des connexions |
| `python manage.py entrainer_triage` | réentraîner le modèle de lecture du texte |
| `python manage.py entrainer_specialite` | réentraîner le modèle d'orientation |
| `python manage.py tester_ia --phrase "Ça me serre la poitrine"` | essayer le triage sur une phrase |
| `python manage.py charger_symptomes` | charger ou mettre à jour le catalogue de symptômes |
| `python manage.py charger_demo` | créer des patients de démonstration |
| `python manage.py audit_accessibilite --patient USER --admin USER` | auditer l'accessibilité des pages |

---

## 13. Documents d'explication

Dans `docs/` :

| Document | Contenu |
|---|---|
| `Parcours_Patient_MediConnect.pdf` | le parcours du patient en un schéma, avec le modèle utilisé à chaque étape |
| `Modeles_IA_MediConnect.pdf` | les six outils : entrée, traitement, sortie, nom, chiffres |
| `Schema_Triage_et_File_Attente.pdf` | le triage, la file, l'agenda et l'attente maximale par niveau |
| `Triage_et_IA_MediConnect.pdf` | explication détaillée du triage et de l'IA |
| `Logique_File_Attente_MediConnect.pdf` | logique de la file d'attente et simulation |
| `Accessibilite_MediConnect.pdf` | rapport d'accessibilité avec les contrastes mesurés |
| `Soins_a_domicile_MediConnect.pdf` | le module infirmiers : parcours, compte rendu intelligent, métriques de l'IA |
| `Validation_Finale_MediConnect.pdf` | chaque critère de la grille de validation et sa preuve |
| `lighthouse/` | rapports Lighthouse (accessibilité, bonnes pratiques) des pages de chaque rôle |

---

## 14. Limites assumées

* Les modèles ont appris sur des phrases **générées**, pas sur de vrais patients : ce sont des **prototypes**.
* Les tests à la main portent sur peu de phrases (39 et 30).
* L'heure prévue est une **estimation** : le système ne sait pas quand le médecin termine ; le statut doit être mis à jour.
* Délais, seuils et durées sont des **valeurs de démonstration**, à faire valider par un professionnel de santé.
* Aucun outil ne pose de diagnostic : en cas de doute, la médecine générale et le médecin décident.

---

## 15. Branches Git

| Branche | Rôle |
|---|---|
| `preprod` | pré-production : chaque module y arrive par Pull Request, après les tests de l'intégration continue |
| `main` | version de référence de l'équipe |
| `gestion-patient` | module patients et back-office (Ismail) |
| `gestion-medecins` | module médecins (Mourad) |
| `gestion-infirmiers` | module infirmiers (Walid) |
| `Pharmacie` | module pharmacies (Ahmed) |
