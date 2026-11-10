# Utilitaires de texte et de prix (sans dépendance vers le reste de l'app).

import json
import math
import re
import unicodedata
from datetime import datetime


def _is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def norm_text(value):
    """Texte sur une seule ligne, espaces multiples réduits (certaines cellules contiennent des retours à la ligne)."""
    return " ".join(str(value).split())


def fold(text):
    """Minuscules sans accents, pour comparer des noms sans se soucier de la saisie."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _to_price(value):
    """Convertit une cellule (ou une saisie) en prix (float) ou None.
    Accepte les nombres, mais aussi le texte : '4 990,00 €', '4990.5', '1.234,56', '1.234' (= 1 234)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            price = float(value)
        except OverflowError:
            return None
        return price if math.isfinite(price) else None
    s = str(value).strip()
    for junk in (" ", " ", " ", "€", "EUR", "HT", "TTC"):
        s = s.replace(junk, "")
    if "," not in s and re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")  # '1.234' : point = séparateur de milliers (à la française)
    s = s.replace(",", ".")
    if s.count(".") > 1:  # séparateurs de milliers : '1.234.56' → '1234.56'
        head, _, tail = s.rpartition(".")
        s = head.replace(".", "") + "." + tail
    try:
        price = float(s)
        return price if math.isfinite(price) else None
    except ValueError:
        return None


def fmt_eur(value):
    """Prix au format français, ex. « 1 350,00 € » (espaces insécables : le prix ne se coupe pas)."""
    return f"{value:,.2f}".replace(",", "\u00a0").replace(".", ",") + "\u00a0€"


def fmt_input(value):
    """Prix dans un champ de saisie, ex. « 1350,00 » (sans espace : plus simple à corriger)."""
    return f"{value:.2f}".replace(".", ",")


def matches_search(name, query):
    """Recherche souple : ni accents ni majuscules, et tous les mots tapés doivent figurer
    dans le nom, dans n'importe quel ordre (« ecran dell 24 » trouve « Écran 24'' DELL »)."""
    folded = fold(name)
    return all(word in folded for word in fold(query).split())


def default_order_name():
    return f"Commande du {datetime.now().strftime('%d/%m %H:%M')}"


def describe_error(err):
    """Message court en français pour une erreur affichée à l'utilisateur (le détail va dans le journal).
    Les erreurs de validation de l'app (CatalogueError, ValueError) sont déjà rédigées en français : conservées."""
    import errno
    if isinstance(err, OSError):
        reasons = {errno.ENOSPC: "Espace de stockage insuffisant", errno.EACCES: "Accès refusé",
                   errno.EPERM: "Accès refusé", errno.ENOENT: "Fichier introuvable",
                   errno.EROFS: "Stockage en lecture seule"}
        return reasons.get(err.errno, "Erreur d'accès au fichier")
    if isinstance(err, (UnicodeDecodeError, json.JSONDecodeError)):
        return "Fichier illisible"
    if isinstance(err, ValueError) or type(err).__name__ == "CatalogueError":
        return str(err)
    return "Erreur inattendue"
