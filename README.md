# MediConnect : module gestion patient

Application Django (Python 3.13) avec une base MongoDB Atlas. Ce module couvre le compte patient, le dossier médical,
la demande de rendez-vous avec triage, la file d'attente équitable, l'agenda prévisionnel, les e-mails et le back-office.

## Installer et lancer sur un autre ordinateur

Il faut **Python 3.13** (3.11 ou plus convient) et **Git**.

```bash
git clone https://github.com/smailch/Esprit-django--5TWIN1-2027-MediConnect.git
cd Esprit-django--5TWIN1-2027-MediConnect
git checkout gestion-patient
python -m venv .venv
.venv\Scripts\activate            # Windows (Linux/Mac : source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env            # Linux/Mac : cp .env.example .env
```

Ouvrir le fichier `.env` et renseigner :

| Variable | Valeur |
|---|---|
| `MONGODB_URI` | l'adresse de connexion MongoDB Atlas (à demander à l'équipe) |
| `MONGODB_NAME` | le nom de la base (`mediconnect`) |
| `DJANGO_SECRET_KEY` | une phrase longue au hasard |
| `DJANGO_DEBUG` | `True` en développement |

**Autoriser l'ordinateur sur Atlas** : dans Atlas, projet MediConnect, *Network Access*, *Add Current IP Address*.
Sans cela, le site démarre mais affiche « SSL handshake failed » au moindre accès à la base.

```bash
python manage.py migrate                  # crée les tables (inutile si l'on utilise la base partagée déjà prête)
python manage.py charger_symptomes        # catalogue de symptômes du triage
python manage.py charger_demo             # facultatif : patients de démonstration (identifiants préfixés demo_)
python manage.py runserver
```

Le site est alors sur http://127.0.0.1:8000/.

## Les modèles d'intelligence artificielle sont dans le dépôt

Les deux petits modèles (lecture du texte du triage et orientation vers une spécialité) sont déjà entraînés et versionnés
dans `ia/artefacts/` : **rien à télécharger ni à entraîner**. Ils utilisent `scikit-learn`, dont la version est figée dans
`requirements.txt` pour que les fichiers `.joblib` se relisent à l'identique.

Si un modèle est illisible (autre version de la bibliothèque, fichier abîmé), il est **réentraîné automatiquement** en quelques
secondes au premier usage. On peut aussi le refaire à la main :

```bash
python manage.py entrainer_triage        # modèle de lecture du texte du triage
python manage.py entrainer_specialite    # modèle d'orientation vers une spécialité
```

## Facultatif

* **IA de langage** (Groq, gratuit) : voir la section IA de `.env.example`. Sans clé, tout fonctionne avec les règles et les modèles locaux.
* **E-mails réels** : voir la section e-mail de `.env.example`. Sans réglage, les messages s'affichent dans la console du serveur.

## Vérifier que tout fonctionne

```bash
python manage.py check
python manage.py test ia patients backoffice core     # tests rapides, sans base de données
```

## Documents

Le dossier `docs/` contient les PDF d'explication : schéma du triage et de la file, modèles et algorithmes,
parcours du patient, accessibilité.
