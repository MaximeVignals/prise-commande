"""Modèles de commandes sans prix mémorisés ni dépendance à l'interface."""

import json as _json
import re as _re
import uuid as _uuid
from datetime import datetime as _datetime

if __package__:
    from . import config as _config, storage as _storage
    from .text import norm_text as _norm_text
else:
    import config as _config
    import storage as _storage
    from text import norm_text as _norm_text


__all__ = [
    "templates_path", "load_templates", "save_templates", "new_template_id",
    "template_from_order", "resolve_template", "line_price", "build_order_items", "items_total",
]


def templates_path():
    return _storage.storage_dir() / _config.TEMPLATES_FILENAME


def load_templates():
    """Charge les modèles valides et met de côté un fichier illisible."""
    path = templates_path()
    data, warning = _storage.read_json(path)
    if warning or (data is None and not path.exists()):
        return {}, warning
    if not isinstance(data, dict):
        return {}, _storage._set_aside(path, "format inattendu")

    templates = {}
    for template_id, template in data.items():
        if (not isinstance(template, dict) or not isinstance(template.get("name"), str)
                or not template["name"].strip() or not isinstance(template.get("entries"), list)):
            continue
        entries = []
        for entry in template["entries"]:
            if not isinstance(entry, dict):
                continue
            if not all(isinstance(entry.get(field), str) for field in ("key", "catalogue", "category", "name")):
                continue
            if (not entry["key"].strip() or not entry["name"].strip()
                    or type(entry.get("quantite")) is not int or entry["quantite"] <= 0):
                continue
            entries.append({field: entry[field] for field in ("key", "catalogue", "category", "name", "quantite")})
        if entries:
            templates[str(template_id)] = {
                "name": template["name"].strip(),
                "created": _storage._valid_iso(template.get("created")),
                "entries": entries,
            }
    return templates, None


def save_templates(templates):
    _storage.write_json(templates_path(), templates)


def new_template_id(existing):
    while True:
        template_id = _uuid.uuid4().hex[:8]
        if template_id not in existing:
            return template_id


def template_from_order(order, catalogue_entries, name):
    """Ne conserve que l'identité des articles et leurs quantités."""
    name = name.strip()
    if not name or not order.get("items"):
        raise ValueError("Le modèle doit avoir un nom et au moins un article.")
    articles = {article["Cle"]: article for article in catalogue_entries}
    entries = []
    for key, item in order["items"].items():
        article = articles.get(key)
        catalogue, category, article_name = _config.DEFAULT_CATALOGUE, "", item["Nom"]
        if article is not None:
            catalogue, category, article_name = article["Catalogue"], article["Categorie"], article["Nom_Article"]
        elif key.startswith(_config.KEY_CATALOGUE):
            # Le suffixe de doublon n'appartient pas au tableau JSON de la clé.
            raw_key = _re.sub(r" \(\d+\)$", "", key[len(_config.KEY_CATALOGUE):])
            try:
                parts = _json.loads(raw_key)
                if isinstance(parts, list) and len(parts) == 2 and all(isinstance(part, str) for part in parts):
                    catalogue = parts[0]
            except ValueError:
                pass
        entries.append({"key": key, "catalogue": catalogue, "category": category,
                        "name": article_name, "quantite": int(item["quantite"])})
    return {"name": name, "created": _datetime.now().isoformat(timespec="minutes"), "entries": entries}


def _base_key(entry):
    """Clé qu'aurait un article importé sans homonyme. Une autre clé (suffixe « (2) » ajouté
    à l'import) dépend de l'ordre des lignes : elle ne désigne pas un article de façon fiable."""
    catalogue, name = _norm_text(entry["catalogue"]), _norm_text(entry["name"])  # comme à l'import
    if catalogue:
        return _config.KEY_CATALOGUE + _json.dumps([catalogue, name], ensure_ascii=False)
    return _config.KEY_EXCEL + name


def _is_duplicate_key(entry):
    """Clé = clé de base + « (2) », « (3) »… : homonyme numéroté selon l'ordre des lignes à l'import.
    Un article dont le vrai nom finit par « (2) » a une clé de base et n'est donc pas concerné."""
    return _re.fullmatch(_re.escape(_base_key(entry)) + r" \(\d+\)", entry["key"]) is not None


def resolve_template(template, catalogue_entries, hidden_catalogues):
    """Résout chaque ligne sans deviner l'identité des doublons importés."""
    catalogue_entries = list(catalogue_entries)
    lines = []
    for entry in template["entries"]:
        personal = entry["key"].startswith(_config.KEY_PERSO)
        if personal:
            candidates = [article for article in catalogue_entries if article["Cle"] == entry["key"]]
        else:
            # Seuls les articles importés peuvent remplacer un article importé (jamais un article perso).
            candidates = [article for article in catalogue_entries
                          if not article.get("Perso")
                          and _norm_text(article["Catalogue"]) == _norm_text(entry["catalogue"])
                          and _norm_text(article["Nom_Article"]) == _norm_text(entry["name"])]
        moved = (not personal and len(candidates) == 1 and entry["category"]
                 and _norm_text(candidates[0]["Categorie"]) != _norm_text(entry["category"]))
        article = None
        if not candidates:
            status = "missing"
        elif len(candidates) > 1 or moved or (not personal and _is_duplicate_key(entry)):
            status = "ambiguous"
        else:
            article = candidates[0]
            status = "hidden" if not article["Visible"] or article["Catalogue"] in hidden_catalogues else "ok"
        lines.append({"entry": entry, "status": status, "article": article, "candidates": candidates})
    return lines


def line_price(article):
    return float(article["Prix_Unitaire"])


def build_order_items(choices):
    """Assemble les choix au prix actuel en regroupant les quantités."""
    items = {}
    for article, quantite in choices:
        quantite = int(quantite)
        if quantite <= 0:
            continue
        key = article["Cle"]
        if key in items:
            items[key]["quantite"] += quantite
        else:
            items[key] = {"Nom": article["Nom_Article"], "Prix": line_price(article), "quantite": quantite}
    return items


def items_total(items):
    return sum(item["Prix"] * item["quantite"] for item in items.values())
