# Lecture, installation et assemblage du catalogue (xlsx/csv au format de FORMAT_CATALOGUE.md).

import csv
import io
import json
import os

from openpyxl import load_workbook

if __package__:
    from .config import (CATALOGUE_COLUMNS, CATALOGUE_EXTENSIONS, CATALOGUE_STEM, DEFAULT_CATALOGUE, KEY_CATALOGUE, KEY_EXCEL,
                         REQUIRED_COLUMNS, SAMPLE_CATALOGUE_FILENAME, YES_VALUES)
    from .text import _is_empty, _to_price, fold, norm_text
    from .storage import assets_dir, storage_dir
else:
    from config import (CATALOGUE_COLUMNS, CATALOGUE_EXTENSIONS, CATALOGUE_STEM, DEFAULT_CATALOGUE, KEY_CATALOGUE, KEY_EXCEL,
                        REQUIRED_COLUMNS, SAMPLE_CATALOGUE_FILENAME, YES_VALUES)
    from text import _is_empty, _to_price, fold, norm_text
    from storage import assets_dir, storage_dir


class CatalogueError(Exception):
    """Fichier catalogue qui ne respecte pas le format (message affiché tel quel à l'utilisateur)."""


def catalogue_path():
    """Catalogue importé (dans le stockage de l'app), ou None s'il n'y en a pas encore."""
    for ext in CATALOGUE_EXTENSIONS:
        path = storage_dir() / (CATALOGUE_STEM + ext)
        if path.exists():
            return path
    return None


def sample_catalogue_path():
    return assets_dir() / SAMPLE_CATALOGUE_FILENAME


def split_catalogue_category(value):
    """Préfixe facultatif « Tarif matériel:Caméra », sans crochets."""
    value = norm_text(value)
    if ":" not in value:
        return DEFAULT_CATALOGUE, value
    catalogue, category = (part.strip() for part in value.split(":", 1))
    if not catalogue or not category:
        raise ValueError("catalogue ou catégorie vide")
    return catalogue, category


def _read_rows(data, ext):
    """Lignes brutes (listes de valeurs) d'un .xlsx (1re feuille) ou d'un .csv (; , ou tabulation)."""
    if ext == ".xlsx":
        try:
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as err:
            raise CatalogueError(f"Fichier Excel illisible ({err}).")
        try:
            return [list(row) for row in wb.worksheets[0].iter_rows(values_only=True)]
        finally:
            wb.close()
    if ext == ".csv":
        for encoding in ("utf-8-sig", "cp1252"):  # UTF-8 (Gemini, Google Sheets) ou Excel Windows
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise CatalogueError("Encodage CSV illisible : enregistrez le fichier en UTF-8.")
        first_line = next((line for line in text.splitlines() if line.strip()), "")
        delimiter = max(";,\t", key=first_line.count)
        return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    raise CatalogueError("Format non pris en charge : choisissez un fichier .xlsx ou .csv.")


def parse_catalogue(data, ext):
    """Lit un catalogue au format « Catégorie | Article | Prix | Masqué » (voir FORMAT_CATALOGUE.md).
    Retourne (articles, lignes_ignorées). Articles : Cle, Nom_Article, Catalogue, Categorie, Prix_Excel, Masque.
    Lève CatalogueError si le fichier est inutilisable (en-têtes manquants, aucun article)."""
    rows = _read_rows(data, ext.lower())
    # Ligne d'en-têtes = 1re ligne non vide
    while rows and all(_is_empty(v) for v in rows[0]):
        rows.pop(0)
    if not rows:
        raise CatalogueError("Le fichier est vide.")
    headers = [fold(norm_text(v)) if not _is_empty(v) else "" for v in rows[0]]
    columns = {}
    for field, label in CATALOGUE_COLUMNS.items():
        if fold(label) in headers:
            columns[field] = headers.index(fold(label))
    missing = [CATALOGUE_COLUMNS[f] for f in REQUIRED_COLUMNS if f not in columns]
    if missing:
        raise CatalogueError(
            "Colonne(s) manquante(s) : " + ", ".join(f"« {m} »" for m in missing) + ".\n"
            "La ligne 1 doit contenir : " + " | ".join(CATALOGUE_COLUMNS.values()) + ".")

    def cell(row, field):
        i = columns.get(field)
        return row[i] if i is not None and i < len(row) else None

    items, skipped, used_keys = [], [], set()
    for line_no, row in enumerate(rows[1:], start=2):
        if all(_is_empty(v) for v in row):
            continue
        name, category, raw_price = cell(row, "article"), cell(row, "categorie"), cell(row, "prix")
        price = _to_price(raw_price)
        if _is_empty(name):
            skipped.append(f"ligne {line_no} : article sans nom")
            continue
        name = norm_text(name)
        if _is_empty(category):
            skipped.append(f"ligne {line_no} : « {name} » sans catégorie")
            continue
        try:
            catalogue, category = split_catalogue_category(category)
        except ValueError:
            skipped.append(f"ligne {line_no} : « {name} » catalogue ou catégorie vide")
            continue
        if price is None or price < 0:
            skipped.append(f"ligne {line_no} : « {name} » prix illisible ({raw_price!r})")
            continue

        # Les clés historiques restent identiques pour les catégories sans préfixe.
        # Un catalogue nommé possède ses propres articles, même si les noms sont identiques.
        base_key = (KEY_CATALOGUE + json.dumps([catalogue, name], ensure_ascii=False)
                    if catalogue else KEY_EXCEL + name)
        key = base_key
        n = 2
        while key in used_keys:  # deux articles portant le même nom
            key = f"{base_key} ({n})"
            n += 1
        used_keys.add(key)

        hidden = cell(row, "masque")
        items.append({
            "Cle": key,
            "Nom_Article": name,
            "Catalogue": catalogue,
            "Categorie": category,
            "Prix_Excel": price,
            "Masque": not _is_empty(hidden) and fold(norm_text(hidden)) in YES_VALUES,
        })
    if not items:
        raise CatalogueError("Aucun article valide dans le fichier.\n" + "\n".join(skipped[:5]))
    return items, skipped


def load_catalogue():
    """Catalogue importé, ou [] s'il n'y en a pas (ou s'il est devenu illisible)."""
    path = catalogue_path()
    if path is None:
        return []
    try:
        return parse_catalogue(path.read_bytes(), path.suffix)[0]
    except (OSError, CatalogueError) as err:
        print(f"[catalogue] {path.name} illisible : {err}")
        return []


def install_catalogue(data, ext):
    """Vérifie puis enregistre un catalogue dans le stockage de l'app (remplace le précédent).
    Retourne (articles, lignes_ignorées). Lève CatalogueError sans rien changer si le fichier est invalide."""
    ext = ext.lower()
    items, skipped = parse_catalogue(data, ext)
    storage_dir().mkdir(parents=True, exist_ok=True)
    target = storage_dir() / (CATALOGUE_STEM + ext)
    tmp = target.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    for other in CATALOGUE_EXTENSIONS:  # un seul fichier importé à la fois
        if other != ext:
            (storage_dir() / (CATALOGUE_STEM + other)).unlink(missing_ok=True)
    return items, skipped


def build_catalogue(excel_items, prefs):
    """Catalogue utilisé par l'app : articles Excel + articles ajoutés, avec prix modifiés et visibilité."""
    entries = []
    for it in prefs.get("catalogue_items", excel_items):
        key = it["Cle"]
        entries.append({
            "Cle": key,
            "Nom_Article": it["Nom_Article"],
            "Catalogue": it.get("Catalogue", DEFAULT_CATALOGUE),
            "Categorie": it["Categorie"],
            "Prix_Unitaire": prefs["prices"].get(key, it["Prix_Excel"]),
            "Prix_Excel": it["Prix_Excel"],
            "Perso": False,
            "Visible": key not in prefs["hidden"],
        })
    for c in prefs["custom"]:
        entries.append({
            "Cle": c["key"],
            "Nom_Article": c["name"],
            "Catalogue": c.get("catalogue", DEFAULT_CATALOGUE),
            "Categorie": c["category"],
            "Prix_Unitaire": c["price"],
            "Prix_Excel": None,
            "Perso": True,
            "Visible": c["key"] not in prefs["hidden"],
        })
    return entries


def categories_of(entries):
    """Catégories dans l'ordre d'apparition (Excel d'abord, puis catégories créées dans l'app)."""
    return list(dict.fromkeys(e["Categorie"] for e in entries))


def catalogues_of(entries):
    """Catalogues dans l'ordre du fichier, y compris ceux dont tous les articles sont masqués."""
    return list(dict.fromkeys(e["Catalogue"] for e in entries))
