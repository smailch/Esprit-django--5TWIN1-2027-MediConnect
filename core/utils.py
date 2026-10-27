from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404


def objet_ou_404(source, **filtres):
    """`get_object_or_404` qui répond « introuvable » (404) et non « erreur serveur » (500)
    quand l'identifiant de l'adresse n'a pas le format d'un ObjectId MongoDB
    (par exemple /triage/pas-un-id/)."""
    try:
        return get_object_or_404(source, **filtres)
    except ValidationError:
        raise Http404("Identifiant invalide.")


def proteger_tableur(texte):
    """Un texte qui commence par = + - @ serait exécuté comme une formule par un tableur : on le précède d'une apostrophe."""
    return "'" + texte if texte[:1] in ("=", "+", "-", "@") else texte
