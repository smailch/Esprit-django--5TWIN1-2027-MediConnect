"""Contrôles d'accessibilité réutilisables (logique pure) : contraste WCAG et structure d'une page HTML.

Servent aux tests automatiques et à la commande `manage.py audit_accessibilite`. Ils ne remplacent pas un audit
complet (Lighthouse, axe), mais détectent les défauts les plus courants et empêchent qu'ils reviennent.
"""
import collections
from html.parser import HTMLParser

SEUIL_TEXTE_NORMAL = 4.5  # WCAG AA : texte courant
SEUIL_GROS_TEXTE = 3.0  # WCAG AA : texte d'au moins 18,66 px en gras ou 24 px


def luminance(couleur):
    """Luminance relative WCAG d'une couleur « #RRGGBB »."""
    c = couleur.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def contraste(a, b):
    """Rapport de contraste WCAG entre deux couleurs (de 1 à 21)."""
    clair, sombre = sorted((luminance(a), luminance(b)), reverse=True)
    return (clair + 0.05) / (sombre + 0.05)


class _Analyse(HTMLParser):
    VIDES = {"br", "hr", "img", "input", "meta", "link", "source", "area", "base", "col", "embed", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.pile, self.titres, self.reperes = [], [], collections.Counter()
        self.ids, self.etiquettes, self.champs, self.liens_boutons = collections.Counter(), set(), [], []
        self.images, self.icones, self.tabindex_positifs, self.navs = [], [], 0, []
        self.langue, self.titre_page, self.dans_titre, self.th, self.th_sans_scope = None, "", False, 0, 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.langue = a.get("lang")
        elif tag == "title":
            self.dans_titre = True
        elif tag in ("main", "header", "footer"):
            self.reperes[tag] += 1
        elif tag == "nav":
            self.reperes["nav"] += 1
            self.navs.append(a.get("aria-label") or a.get("aria-labelledby"))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.titres.append(int(tag[1]))
        elif tag == "label" and a.get("for"):
            self.etiquettes.add(a["for"])
        elif tag in ("input", "select", "textarea") and a.get("type") not in ("hidden", "submit", "button"):
            self.champs.append((a, any(kind == "label" for kind, _ in self.pile)))
        elif tag == "img":
            self.images.append(a)
        elif tag == "i" and "data-lucide" in a:
            self.icones.append(a)
        elif tag == "th":
            self.th += 1
            self.th_sans_scope += "scope" not in a
        if a.get("id"):
            self.ids[a["id"]] += 1
        try:
            if int(a.get("tabindex", "0")) > 0:
                self.tabindex_positifs += 1
        except ValueError:
            pass
        if tag in ("a", "button"):
            self.liens_boutons.append({"tag": tag, "a": a, "texte": ""})
            self.pile.append(("acces", len(self.liens_boutons) - 1))
        elif tag not in self.VIDES:
            self.pile.append((tag, None))

    def handle_endtag(self, tag):
        if tag == "title":
            self.dans_titre = False
        for i in range(len(self.pile) - 1, -1, -1):
            nom = self.pile[i][0]
            if nom == tag or (nom == "acces" and tag in ("a", "button")):
                del self.pile[i:]
                break

    def handle_data(self, data):
        if self.dans_titre:
            self.titre_page += data
        if data.strip():
            for kind, idx in self.pile:
                if kind == "acces":
                    self.liens_boutons[idx]["texte"] += data.strip()


def verifier_html(html):
    """Liste des défauts d'accessibilité repérés dans une page HTML complète (liste vide : rien à signaler)."""
    a = _Analyse()
    a.feed(html)
    problemes = []
    if not a.langue:
        problemes.append("<html> sans attribut lang")
    if not a.titre_page.strip():
        problemes.append("<title> vide")
    if a.reperes["main"] != 1:
        problemes.append(f"{a.reperes['main']} élément(s) <main> (il en faut un seul)")
    if a.reperes["footer"] == 0:
        problemes.append("pas de <footer>")
    if any(not nom for nom in a.navs):
        problemes.append("<nav> sans aria-label")
    if a.titres.count(1) != 1:
        problemes.append(f"{a.titres.count(1)} titre(s) h1 (il en faut un seul)")
    for avant, apres in zip(a.titres, a.titres[1:]):
        if apres > avant + 1:
            problemes.append(f"saut dans la hiérarchie des titres : h{avant} puis h{apres}")
            break
    problemes += [f"identifiant en double : {i}" for i, n in a.ids.items() if n > 1]
    for attrs, dans_label in a.champs:
        if not (attrs.get("aria-label") or attrs.get("aria-labelledby") or attrs.get("title") or attrs.get("id") in a.etiquettes or dans_label):
            problemes.append(f"champ sans étiquette : {attrs.get('name')}")
    for lb in a.liens_boutons:
        if not (lb["texte"] or lb["a"].get("aria-label") or lb["a"].get("title")):
            problemes.append(f"{lb['tag']} sans nom accessible : {lb['a'].get('href') or lb['a'].get('class')}")
    problemes += [f"image sans alt : {im.get('src')}" for im in a.images if "alt" not in im]
    exposees = sum(1 for ic in a.icones if ic.get("aria-hidden") != "true")
    if exposees:
        problemes.append(f"{exposees} icône(s) sans aria-hidden")
    if a.tabindex_positifs:
        problemes.append(f"{a.tabindex_positifs} tabindex positif(s)")
    if a.th_sans_scope:
        problemes.append(f"{a.th_sans_scope} cellule(s) <th> sans scope")
    return problemes


# --- contrastes du projet : les couleurs sont LUES dans les fichiers CSS, pas recopiées -------------------------
import re
from pathlib import Path

DOSSIER_CSS = Path(__file__).resolve().parent.parent / "static" / "css"
TEXTE_SOMBRE_DES_BADGES = "#0B1220"  # couleur du texte sur les pastilles de niveau et de gravité (voir .lv et .sev)


def couleurs_css(*fichiers):
    """{'--a-text': '#E6EEF8', …} : les variables de couleur « #RRGGBB » déclarées dans les fichiers CSS."""
    couleurs = {}
    for nom in fichiers:
        texte = (DOSSIER_CSS / nom).read_text(encoding="utf-8")
        couleurs.update({k: v.upper() for k, v in re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b", texte)})
    return couleurs


def contrastes_du_projet():
    """[(description, couleur du texte, couleur du fond, rapport)] pour les combinaisons utilisées par l'interface."""
    c = couleurs_css("app.css", "ui.css")
    paires = [
        ("texte principal sur le fond", c["--a-text"], c["--a-bg"]), ("texte principal sur une carte", c["--a-text"], c["--a-surface"]),
        ("texte atténué sur le fond", c["--a-muted"], c["--a-bg"]), ("texte atténué sur une carte", c["--a-muted"], c["--a-surface"]),
        ("texte atténué sur une carte surélevée", c["--a-muted"], c["--a-raise"]),
        ("lien et accent sur le fond", c["--a-accent"], c["--a-bg"]), ("lien et accent sur une carte", c["--a-accent"], c["--a-surface"]),
        ("bouton principal (texte sombre sur accent)", c["--a-accent-ink"], c["--a-accent"]),
        ("accueil : texte principal", c["--text"], c["--bg"]), ("accueil : texte atténué", c["--muted"], c["--bg"]),
        ("accueil : lien cyan", c["--cyan-text"], c["--bg"]),
    ]
    paires += [(f"pastille niveau/gravité {n}", TEXTE_SOMBRE_DES_BADGES, c[f"--u{n}"]) for n in range(1, 6)]
    return [(nom, fg, bg, round(contraste(fg, bg), 2)) for nom, fg, bg in paires]
