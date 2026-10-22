"""Client d'IA (modèle de langage) : Groq (cloud gratuit) ou Ollama (sur le serveur).

Les deux services parlent le même protocole (« compatible OpenAI ») : un seul code, choisi dans `.env`.
Aucune dépendance externe (urllib). L'IA est désactivée tant que IA_FOURNISSEUR n'est pas réglé.

Principes : jamais d'exception vers l'appelant (toute panne devient un ResultatIA sans données, l'application
retombe sur ses règles), délai maximal court, réponse JSON uniquement, résultats mis en cache, clé d'API jamais
affichée ni écrite dans les journaux.
"""
import hashlib
import json
import logging
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from django.conf import settings
from django.core.cache import cache

journal = logging.getLogger("mediconnect.ia")

VERSION_PROMPTS = "1"  # à changer quand un prompt change : les anciens résultats en cache sont alors ignorés
DUREE_CACHE = 3600
QUOTA_PAR_HEURE = 20  # appels par patient et par heure : protège la limite gratuite du fournisseur

FOURNISSEURS = {
    "groq": {
        "nom": "Groq (service cloud)",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "modele": "qwen/qwen3.8-27b",  # vérifié avec une vraie clé le 22/10/2026 ; llama-3.3 n'existe plus chez Groq
        "cle_requise": True,
        "local": False,
    },
    "ollama": {
        "nom": "Ollama (sur le serveur MediConnect)",
        "url": "http://localhost:11434/v1/chat/completions",
        "modele": "qwen2.5:3b",
        "cle_requise": False,
        "local": True,
    },
}

OK, NON_CONFIGUREE, DELAI, RESEAU, ERREUR_HTTP, LIMITE, INVALIDE, QUOTA, ABSENT = (
    "ok", "non_configuree", "delai", "reseau", "erreur_http", "limite", "reponse_invalide", "quota", "absent",
)
MESSAGES = {
    OK: "Connexion réussie.",
    NON_CONFIGUREE: "L'IA n'est pas configurée (voir IA_FOURNISSEUR et la clé dans le fichier .env).",
    DELAI: "Le service d'IA n'a pas répondu à temps.",
    RESEAU: "Impossible de joindre le service d'IA.",
    ERREUR_HTTP: "Le service d'IA a refusé la demande (clé invalide ou modèle inconnu ?).",
    LIMITE: "La limite gratuite du service d'IA est atteinte pour le moment.",
    INVALIDE: "Le service d'IA a répondu dans un format inattendu.",
    QUOTA: "Trop d'analyses IA ont été demandées cette heure-ci.",
    ABSENT: "Aucune analyse IA récente.",
}


@dataclass(frozen=True)
class Config:
    fournisseur: str
    url: str
    modele: str
    cle: str
    delai: float


@dataclass
class ResultatIA:
    statut: str
    donnees: dict | None = None
    duree_ms: int = 0
    en_cache: bool = False
    http: int = 0
    details: list = field(default_factory=list)

    @property
    def ok(self):
        return self.statut == OK and self.donnees is not None

    @property
    def message(self):
        return MESSAGES.get(self.statut, "")


def configuration():
    """Configuration active, ou None si l'IA est désactivée ou incomplète (clé manquante, par exemple)."""
    fournisseur = (getattr(settings, "IA_FOURNISSEUR", "aucun") or "aucun").strip().lower()
    defauts = FOURNISSEURS.get(fournisseur)
    if defauts is None:
        return None
    cle = (getattr(settings, "IA_CLE_API", "") or "").strip()
    if defauts["cle_requise"] and not cle:
        return None
    return Config(
        fournisseur=fournisseur,
        url=(getattr(settings, "IA_URL", "") or "").strip() or defauts["url"],
        modele=(getattr(settings, "IA_MODELE", "") or "").strip() or defauts["modele"],
        cle=cle,
        delai=float(getattr(settings, "IA_DELAI_MAX", 6) or 6),
    )


def est_active():
    return configuration() is not None


def description():
    """Ce qu'on peut afficher sans risque (jamais la clé)."""
    fournisseur = (getattr(settings, "IA_FOURNISSEUR", "aucun") or "aucun").strip().lower()
    defauts = FOURNISSEURS.get(fournisseur)
    config = configuration()
    return {
        "fournisseur": fournisseur,
        "nom": defauts["nom"] if defauts else "Aucun",
        "modele": config.modele if config else "",
        "hote": urlparse(config.url).netloc if config else "",
        "cle_requise": defauts["cle_requise"] if defauts else False,
        "cle_presente": bool((getattr(settings, "IA_CLE_API", "") or "").strip()),
        "local": defauts["local"] if defauts else False,
        "active": config is not None,
    }


def _extraire_json(texte):
    """Objet JSON d'une réponse de modèle (tolère les ```json … ```)."""
    texte = re.sub(r"<think>.*?</think>", "", texte or "", flags=re.S).strip()  # certains modèles écrivent leur réflexion d'abord
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte, flags=re.I)
    try:
        valeur = json.loads(texte)
    except ValueError:
        debut, fin = texte.find("{"), texte.rfind("}")
        if debut < 0 or fin <= debut:
            return None
        try:
            valeur = json.loads(texte[debut:fin + 1])
        except ValueError:
            return None
    return valeur if isinstance(valeur, dict) else None


def _cle_de_cache(config, systeme, utilisateur):
    brut = "\x1f".join((VERSION_PROMPTS, config.fournisseur, config.modele, systeme, utilisateur))
    return "ia:" + hashlib.sha256(brut.encode("utf-8")).hexdigest()


def appeler_json(systeme, utilisateur, *, max_tokens=500, utiliser_cache=True, seulement_cache=False):
    """Interroge le modèle et renvoie un ResultatIA. Ne lève jamais d'exception.

    seulement_cache : ne contacte jamais le service (affichage qui ne doit pas déclencher d'appel externe)."""
    config = configuration()
    if config is None:
        return ResultatIA(NON_CONFIGUREE)
    cle_cache = _cle_de_cache(config, systeme, utilisateur)
    if utiliser_cache or seulement_cache:
        en_cache = cache.get(cle_cache)
        if en_cache is not None:
            return ResultatIA(OK, en_cache, en_cache=True)
    if seulement_cache:
        return ResultatIA(ABSENT)

    corps = json.dumps({
        "model": config.modele,
        "messages": [{"role": "system", "content": systeme}, {"role": "user", "content": utilisateur}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    entetes = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "MediConnect/1.0"}
    if config.cle:
        entetes["Authorization"] = f"Bearer {config.cle}"
    requete = urllib.request.Request(config.url, data=corps, headers=entetes, method="POST")

    debut = time.monotonic()
    ms = lambda: int((time.monotonic() - debut) * 1000)  # noqa: E731
    try:
        with urllib.request.urlopen(requete, timeout=config.delai) as reponse:
            brut = reponse.read(200_000)
            statut_http = reponse.status
    except urllib.error.HTTPError as e:
        statut = LIMITE if e.code == 429 else ERREUR_HTTP
        journal.warning("IA %s : HTTP %s en %s ms", config.fournisseur, e.code, ms())
        return ResultatIA(statut, duree_ms=ms(), http=e.code)
    except (socket.timeout, TimeoutError):
        journal.warning("IA %s : délai dépassé (%s s)", config.fournisseur, config.delai)
        return ResultatIA(DELAI, duree_ms=ms())
    except urllib.error.URLError as e:
        raison = e.reason
        statut = DELAI if isinstance(raison, (socket.timeout, TimeoutError)) else RESEAU
        journal.warning("IA %s : %s", config.fournisseur, type(raison).__name__)
        return ResultatIA(statut, duree_ms=ms())
    except OSError as e:
        journal.warning("IA %s : %s", config.fournisseur, type(e).__name__)
        return ResultatIA(RESEAU, duree_ms=ms())

    try:
        contenu = json.loads(brut.decode("utf-8"))["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError, UnicodeDecodeError):
        return ResultatIA(INVALIDE, duree_ms=ms(), http=statut_http)
    donnees = _extraire_json(contenu)
    if donnees is None:
        return ResultatIA(INVALIDE, duree_ms=ms(), http=statut_http)
    if utiliser_cache:
        cache.set(cle_cache, donnees, DUREE_CACHE)
    journal.info("IA %s : ok en %s ms", config.fournisseur, ms())
    return ResultatIA(OK, donnees, duree_ms=ms(), http=statut_http)


def tester_connexion():
    """Appel minimal pour vérifier la clé et le modèle (utilisé par la page Paramètres du back-office)."""
    resultat = appeler_json(
        "Tu réponds uniquement par un objet JSON.", 'Réponds exactement : {"ok": true}', max_tokens=20, utiliser_cache=False
    )
    if resultat.statut == OK and resultat.donnees.get("ok") is not True:
        return ResultatIA(INVALIDE, duree_ms=resultat.duree_ms, http=resultat.http)
    return resultat


def reserver_appel(identifiant, limite=QUOTA_PAR_HEURE):
    """Compte les analyses IA d'un patient sur l'heure en cours. False si la limite est atteinte."""
    cle = f"ia:quota:{identifiant}:{int(time.time() // 3600)}"
    cache.add(cle, 0, 3600)
    try:
        return cache.incr(cle) <= limite
    except ValueError:
        return True
