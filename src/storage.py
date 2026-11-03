# Fichiers de données de l'app : commandes, réglages, photos (lecture/écriture JSON sécurisée).

import json
import math
import os
from datetime import datetime
from pathlib import Path

if __package__:
    from .config import KEY_CATALOGUE, KEY_EXCEL, KEY_PERSO, ORDERS_FILENAME, PREFS_FILENAME
    from .text import _to_price, default_order_name, norm_text
else:
    from config import KEY_CATALOGUE, KEY_EXCEL, KEY_PERSO, ORDERS_FILENAME, PREFS_FILENAME
    from text import _to_price, default_order_name, norm_text


def assets_dir():
    # Dans l'APK / l'exe, Flet fournit le dossier assets via FLET_ASSETS_DIR.
    # En développement (flet run), on retombe sur src/assets/ à côté de ce fichier.
    return Path(os.getenv("FLET_ASSETS_DIR") or str(Path(__file__).parent / "assets"))


# --- FICHIERS DE DONNÉES (commandes et réglages du catalogue) ---


def storage_dir():
    # FLET_APP_STORAGE_DATA = dossier privé et inscriptible de l'app (conservé entre les lancements).
    return Path(os.getenv("FLET_APP_STORAGE_DATA") or os.getcwd())


def orders_path():
    return storage_dir() / ORDERS_FILENAME


def photos_dir(order_id):
    """Dossier des photos d'une commande (dans le stockage privé de l'app)."""
    return storage_dir() / "photos" / str(order_id)


def photo_path(order_id, photo):
    return photos_dir(order_id) / photo["file"]


def prefs_path():
    return storage_dir() / PREFS_FILENAME


def _set_aside(path, reason):
    """Met de côté un fichier illisible (copie datée) pour qu'il ne soit pas écrasé. Retourne un message."""
    backup = path.with_name(f"{path.stem}.illisible-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
    try:
        os.replace(path, backup)
        return (f"Le fichier « {path.name} » était illisible ({reason}).\n"
                f"Il a été conservé sous le nom « {backup.name} ».")
    except OSError as err:
        return f"Le fichier « {path.name} » est illisible ({reason}) et n'a pas pu être mis de côté ({err})."


def read_json(path):
    """Retourne (données, avertissement). Fichier absent → (None, None).
    Fichier illisible → mis de côté au lieu d'être écrasé, avec un avertissement."""
    if not path.exists():
        return None, None
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as err:
        return None, _set_aside(path, err)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)  # écriture atomique : pas de fichier à moitié écrit


def _valid_iso(value):
    try:
        datetime.fromisoformat(str(value))
        return str(value)
    except ValueError:
        return datetime.now().isoformat(timespec="minutes")


def load_orders():
    """Retourne (commandes, id_commande_active, avertissement)."""
    path = orders_path()
    data, warning = read_json(path)
    if data is None:
        return {}, None, warning
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict):
        return {}, None, _set_aside(path, "format inattendu")

    orders = {}
    for order_id, order in data["orders"].items():
        if not isinstance(order, dict):
            continue
        raw_items = order.get("items") if isinstance(order.get("items"), dict) else {}
        items = {}
        for key, line in raw_items.items():
            try:
                clean = {"Nom": norm_text(line["Nom"]), "Prix": float(line["Prix"]),
                         "quantite": int(line["quantite"])}
            except (KeyError, TypeError, ValueError, OverflowError):
                continue
            if clean["quantite"] > 0 and math.isfinite(clean["Prix"]) and clean["Prix"] >= 0:
                if isinstance(line.get("note"), str) and line["note"].strip():
                    clean["note"] = line["note"].strip()
                items[str(key)] = clean
        photos = []
        for photo in order.get("photos") if isinstance(order.get("photos"), list) else []:
            try:
                entry = {"id": str(photo["id"]), "file": os.path.basename(str(photo["file"])),
                         "label": norm_text(photo.get("label") or "") or "Photo",
                         "added": _valid_iso(photo.get("added"))}
            except (KeyError, TypeError, AttributeError):
                continue
            if (photos_dir(order_id) / entry["file"]).exists():  # photo effacée hors de l'app : ignorée
                photos.append(entry)
        orders[str(order_id)] = {
            "name": norm_text(order.get("name") or "") or default_order_name(),
            "created": _valid_iso(order.get("created")),
            "items": items,
            "photos": photos,
        }
        if isinstance(order.get("notes"), str) and order["notes"].strip():
            orders[str(order_id)]["notes"] = order["notes"].strip()
        if order.get("archived") is True:
            orders[str(order_id)]["archived"] = True
    return orders, data.get("current"), None


def save_orders(orders, current_id):
    write_json(orders_path(), {"orders": orders, "current": current_id})


def migrate_cart_keys(orders):
    """Les anciennes versions repéraient les lignes de panier par leur position dans l'Excel (ART_0001…),
    qui change dès qu'on ajoute une ligne au fichier. On les repère désormais par le nom de l'article.
    Retourne True si quelque chose a été converti."""
    changed = False
    for order in orders.values():
        if all(k.startswith((KEY_EXCEL, KEY_CATALOGUE, KEY_PERSO)) for k in order["items"]):
            continue
        changed = True
        new_items = {}
        for key, line in order["items"].items():
            new_key = key if key.startswith((KEY_EXCEL, KEY_CATALOGUE, KEY_PERSO)) else KEY_EXCEL + line["Nom"]
            if new_key in new_items:
                existing = new_items[new_key]
                if abs(existing["Prix"] - line["Prix"]) < 0.005 and existing.get("note") == line.get("note"):
                    existing["quantite"] += line["quantite"]
                    continue
                n = 2
                while f"{new_key} ({n})" in new_items:
                    n += 1
                new_key = f"{new_key} ({n})"
            new_items[new_key] = line
        order["items"] = new_items
    return changed


def load_prefs(excel_items):
    """Réglages des articles et des catalogues (hidden_catalogues = noms des catalogues masqués).
    Retourne (réglages, avertissement)."""
    path = prefs_path()
    data, warning = read_json(path)
    if data is not None and not isinstance(data, dict):
        data, warning = None, _set_aside(path, "format inattendu")

    if data is None:
        # Premier lancement : articles marqués « Masqué » dans le catalogue masqués par défaut
        hidden = {it["Cle"] for it in excel_items if it.get("Masque")}
        return {"hidden": hidden, "hidden_catalogues": set(), "prices": {}, "custom": [],
                "favorites": set(), "recent": []}, warning

    hidden = {str(k) for k in data.get("hidden", [])} if isinstance(data.get("hidden"), list) else set()
    hidden_catalogues = ({name for name in data["hidden_catalogues"] if isinstance(name, str)}
                         if isinstance(data.get("hidden_catalogues"), list) else set())
    prices = {}
    if isinstance(data.get("prices"), dict):
        for k, v in data["prices"].items():
            p = _to_price(v)
            if p is not None and p >= 0:
                prices[str(k)] = p
    custom = []
    for c in data.get("custom", []) if isinstance(data.get("custom"), list) else []:
        try:
            article = {"key": str(c["key"]), "name": norm_text(c["name"]),
                       "category": norm_text(c["category"]), "price": float(c["price"])}
            if isinstance(c.get("catalogue"), str) and c["catalogue"].strip():
                article["catalogue"] = norm_text(c["catalogue"])
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        if (article["key"].startswith(KEY_PERSO) and article["name"] and article["category"]
                and math.isfinite(article["price"]) and article["price"] >= 0):
            custom.append(article)
    prefs = {"hidden": hidden, "hidden_catalogues": hidden_catalogues,
             "prices": prices, "custom": custom,
             "favorites": {k for k in data.get("favorites", []) if isinstance(k, str)}
                          if isinstance(data.get("favorites"), list) else set(),
             "recent": list(dict.fromkeys(k for k in data.get("recent", []) if isinstance(k, str)))[:20]
                       if isinstance(data.get("recent"), list) else []}
    # Copie locale après renommage / suppression. Une liste vide est un catalogue vidé.
    snapshot = data.get("catalogue_items")
    if isinstance(snapshot, list):
        clean, keys = [], set()
        for item in snapshot:
            if not isinstance(item, dict):
                break
            key, name = item.get("Cle"), item.get("Nom_Article")
            catalogue, category = item.get("Catalogue"), item.get("Categorie")
            price = _to_price(item.get("Prix_Excel"))
            if (not isinstance(key, str) or not key.startswith((KEY_EXCEL, KEY_CATALOGUE))
                    or key in keys or not isinstance(name, str) or not name.strip()
                    or not isinstance(catalogue, str) or not isinstance(category, str) or not category.strip()
                    or price is None or price < 0):
                break
            keys.add(key)
            clean.append({"Cle": key, "Nom_Article": name, "Catalogue": catalogue,
                          "Categorie": category, "Prix_Excel": price, "Masque": bool(item.get("Masque"))})
        else:
            prefs["catalogue_items"] = clean
    return prefs, None


def save_prefs(prefs):
    write_json(prefs_path(), {
        "hidden": sorted(prefs["hidden"]),
        "hidden_catalogues": sorted(prefs.get("hidden_catalogues", set())),
        "prices": prefs["prices"],
        "custom": prefs["custom"],
        "favorites": sorted(prefs.get("favorites", set())),
        "recent": prefs.get("recent", [])[:20],
        **({"catalogue_items": prefs["catalogue_items"]} if "catalogue_items" in prefs else {}),
    })
