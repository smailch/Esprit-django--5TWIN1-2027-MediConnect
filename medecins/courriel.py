"""Compte rendu en PDF, envoyé à l'adresse e-mail du compte patient."""

import smtplib
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMessage
from django.utils import timezone
from fpdf import FPDF

from .sms import EchecEnvoi

MARINE = (5, 14, 28)
SARCELLE = (14, 116, 144)
ENCRE = (30, 41, 59)
CIEL = (232, 245, 248)
GRIS = (90, 110, 120)
_ARIAL = Path(r"C:\Windows\Fonts\arial.ttf")
_ARIAL_GRAS = Path(r"C:\Windows\Fonts\arialbd.ttf")


def email_patient(consultation):
    """Adresse du compte patient. Jamais une adresse fixe."""
    patient = getattr(consultation, "patient", None)
    utilisateur = getattr(patient, "user", None)
    email = (getattr(utilisateur, "email", "") or "").strip()
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        return ""
    return email


class _CompteRenduPDF(FPDF):
    """Feuille à en-tête médical : bandeau marine, croix, pied de page confidentiel."""

    def header(self):
        self.set_fill_color(*MARINE)
        self.rect(0, 0, self.w, 34, style="F")
        self.set_fill_color(*SARCELLE)
        self.rect(0, 34, self.w, 2.4, style="F")
        _croix(self, 14, 9, 16)
        _pouls(self, self.w - 58, 22, 40)
        self.set_text_color(255, 255, 255)
        self._texte(16, 34, 10)
        self.cell(0, 8, "MediConnect", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(186, 230, 240)
        self._texte(11, 34, 19)
        self.cell(0, 6, "Compte rendu de consultation")
        self.set_y(44)

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*SARCELLE)
        self.set_line_width(0.4)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.set_text_color(*GRIS)
        self._texte(8)
        self.cell(self.epw - 20, 8, "Document médical confidentiel  |  MediConnect")
        self.cell(20, 8, str(self.page_no()), align="R")

    def _texte(self, taille, x=None, y=None, gras=False):
        if x is not None:
            self.set_xy(x, y)
        style = "B" if gras else ""
        self.set_font(self.police, style, taille)


def pdf_compte_rendu(consultation):
    """PDF du compte rendu, prêt à joindre au message."""
    date = _date(consultation)
    medecin = consultation.medecin_nom or "Médecin"
    if getattr(consultation, "medecin_specialite", ""):
        medecin = f"{medecin} ({consultation.medecin_specialite})"
    pdf = _CompteRenduPDF()
    pdf.police = _police(pdf)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(16, 44, 16)
    pdf.add_page()
    _fiche(
        pdf,
        str(consultation.patient),
        f"{date:%d/%m/%Y %H:%M}" if date else "-",
        medecin,
    )
    for libelle, valeur in (
        ("Motif", consultation.motif),
        ("Compte rendu", consultation.resume),
        ("Diagnostic", consultation.diagnostic),
        ("Prescription", consultation.prescription),
        ("Recommandations", consultation.recommandations),
    ):
        _bloc(pdf, libelle, valeur)
    for acte in _actes(consultation):
        libelle = acte.get_type_display() if hasattr(acte, "get_type_display") else "Acte"
        _bloc(pdf, libelle, getattr(acte, "contenu", ""))
    return bytes(pdf.output())


def envoyer_compte_rendu(consultation):
    """Envoie le PDF. Retourne l'adresse du patient."""
    email = email_patient(consultation)
    if not email:
        raise EchecEnvoi("Ce patient n'a pas d'adresse e-mail utilisable.")
    if not (getattr(settings, "EMAIL_HOST_USER", "") and getattr(settings, "EMAIL_HOST_PASSWORD", "")):
        raise EchecEnvoi(
            "L'envoi Gmail n'est pas prêt : le mot de passe d'application manque dans .env."
        )
    date = _date(consultation)
    quand = f"{date:%d/%m/%Y}" if date else "votre consultation"
    nom = f"compte-rendu-{date:%Y-%m-%d}.pdf" if date else "compte-rendu.pdf"
    message = EmailMessage(
        subject=f"MediConnect — compte rendu du {quand}",
        body=(
            f"Bonjour,\n\n"
            f"Le compte rendu de la consultation du {quand} est joint à ce message (PDF).\n\n"
            f"MediConnect"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[email],
    )
    message.attach(nom, pdf_compte_rendu(consultation), "application/pdf")
    try:
        message.send(fail_silently=False)
    except smtplib.SMTPAuthenticationError as erreur:
        raise EchecEnvoi(
            "Gmail a refusé l'identifiant. Créez un mot de passe d'application "
            "et placez-le dans EMAIL_HOST_PASSWORD."
        ) from erreur
    except (smtplib.SMTPException, OSError) as erreur:
        raise EchecEnvoi("Le message n'a pas pu partir. Réessayez dans un instant.") from erreur
    return {"email": email}


def contexte_envoi(consultation):
    if not getattr(consultation, "pk", None):
        return {"courriel": False, "email": ""}
    return {"courriel": bool(email_patient(consultation)), "email": email_patient(consultation)}


def _date(consultation):
    date = getattr(consultation, "date", None)
    if date and timezone.is_naive(date):
        date = timezone.make_aware(date, timezone.get_current_timezone())
    if date:
        return timezone.localtime(date)
    return None


def _actes(consultation):
    relation = getattr(consultation, "actes", None)
    if relation is None:
        return []
    if hasattr(relation, "all"):
        return list(relation.all())
    return list(relation)


def _police(pdf):
    if _ARIAL.exists() and _ARIAL_GRAS.exists():
        pdf.add_font("Doc", "", str(_ARIAL))
        pdf.add_font("Doc", "B", str(_ARIAL_GRAS))
        return "Doc"
    return "Helvetica"


def _croix(pdf, x, y, taille):
    """Croix médicale blanche dans un cercle sarcelle."""
    pdf.set_fill_color(*SARCELLE)
    pdf.ellipse(x, y, taille, taille, style="F")
    pdf.set_fill_color(255, 255, 255)
    bras = taille * 0.2
    pdf.rect(x + taille / 2 - bras / 2, y + taille * 0.2, bras, taille * 0.6, style="F")
    pdf.rect(x + taille * 0.2, y + taille / 2 - bras / 2, taille * 0.6, bras, style="F")


def _pouls(pdf, x, y, largeur):
    """Tracé d'un pouls, à droite du bandeau."""
    pdf.set_draw_color(186, 230, 240)
    pdf.set_line_width(0.7)
    plat = largeur * 0.28
    points = [
        (x, y),
        (x + plat, y),
        (x + plat + 3, y - 5),
        (x + plat + 7, y + 5),
        (x + plat + 11, y),
        (x + largeur, y),
    ]
    pdf.polyline(points)


def _fiche(pdf, patient, date, medecin):
    y = pdf.get_y()
    pdf.set_fill_color(*CIEL)
    pdf.rect(pdf.l_margin, y, pdf.epw, 24, style="F")
    colonnes = (("Patient", patient), ("Date", date), ("Médecin", medecin))
    largeur = pdf.epw / 3
    for index, (libelle, valeur) in enumerate(colonnes):
        x = pdf.l_margin + index * largeur
        pdf.set_xy(x + 3, y + 3)
        pdf.set_text_color(*SARCELLE)
        pdf._texte(8, gras=True)
        pdf.cell(largeur - 6, 5, libelle)
        pdf.set_xy(x + 3, y + 10)
        pdf.set_text_color(*ENCRE)
        pdf._texte(10)
        pdf.multi_cell(largeur - 6, 5, valeur)
    pdf.set_y(y + 30)


def _bloc(pdf, libelle, valeur):
    valeur = (valeur or "").strip()
    if not valeur:
        return
    if pdf.get_y() > pdf.h - 36:
        pdf.add_page()
    y = pdf.get_y()
    pdf.set_fill_color(*SARCELLE)
    pdf.rect(pdf.l_margin, y + 1, 2.4, 6, style="F")
    pdf.set_xy(pdf.l_margin + 6, y)
    pdf.set_text_color(*MARINE)
    pdf._texte(12, gras=True)
    pdf.cell(0, 8, libelle, new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 6)
    pdf.set_text_color(*ENCRE)
    pdf._texte(11)
    pdf.multi_cell(pdf.epw - 6, 6, valeur)
    pdf.ln(4)
