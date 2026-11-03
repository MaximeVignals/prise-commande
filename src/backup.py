"""Versioned, local-only backups. Archives are validated before touching storage."""

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import uuid
import zipfile

ORDERS = "commandes.json"
PREFS = "catalogue_perso.json"
CATALOGUES = ("catalogue_importe.xlsx", "catalogue_importe.csv")
ROOT_FILES = (ORDERS, PREFS, *CATALOGUES)
MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 5000


@dataclass
class Snapshot:
    files: dict
    orders: dict
    created: str

    @property
    def photo_count(self):
        return sum(len(order.get("photos", [])) for order in self.orders["orders"].values())


def _component(value):
    if (not isinstance(value, str) or not value or len(value) > 200
            or value in (".", "..") or value[-1] in " ."
            or any(c in value for c in '/\\:<>"|?*') or any(ord(c) < 32 for c in value)
            or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL",
                *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError("Nom de fichier ou de commande invalide dans la sauvegarde.")
    return value


def _target(root, relative):
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute():
        raise ValueError("Chemin invalide dans la sauvegarde.")
    for part in parts:
        _component(part)
    target = root.joinpath(*parts)
    if not target.resolve().is_relative_to(root.resolve()):
        raise ValueError("Un fichier sort du dossier de l'application.")
    return target


def _json(data):
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError("Clé JSON en double dans la sauvegarde.")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nombre invalide.")))


def _price(value):
    return type(value) in (int, float) and value >= 0 and value < float("inf")


def _date(value):
    if not isinstance(value, str):
        raise ValueError("Date absente dans la sauvegarde.")
    datetime.fromisoformat(value)


def _validate_orders(data, files):
    if not isinstance(data, dict) or not isinstance(data.get("orders"), dict):
        raise ValueError("Liste des commandes invalide.")
    if data.get("current") is not None and data["current"] not in data["orders"]:
        raise ValueError("Commande active introuvable.")
    photos = set()
    order_ids = set()
    for order_id, order in data["orders"].items():
        _component(order_id)
        if order_id.casefold() in order_ids:
            raise ValueError("Identifiants de commande identiques sous Windows.")
        order_ids.add(order_id.casefold())
        if (not isinstance(order, dict) or not isinstance(order.get("name"), str)
                or not order["name"].strip() or not isinstance(order.get("items"), dict)
                or not isinstance(order.get("photos", []), list)):
            raise ValueError("Commande invalide.")
        _date(order.get("created"))
        if "archived" in order and type(order["archived"]) is not bool:
            raise ValueError("État d'archivage invalide.")
        if "notes" in order and not isinstance(order["notes"], str):
            raise ValueError("Remarques de commande invalides.")
        for key, item in order["items"].items():
            if (not isinstance(item, dict) or not isinstance(item.get("Nom"), str)
                    or not _price(item.get("Prix")) or type(item.get("quantite")) is not int
                    or item["quantite"] <= 0 or ("note" in item and not isinstance(item["note"], str))):
                raise ValueError("Article de commande invalide.")
        ids = set()
        for photo in order.get("photos", []):
            if not isinstance(photo, dict) or not isinstance(photo.get("label"), str):
                raise ValueError("Photo invalide.")
            photo_id, filename = _component(photo.get("id")), _component(photo.get("file"))
            _date(photo.get("added"))
            path = f"photos/{order_id}/{filename}"
            if photo_id in ids or path in photos or path not in files:
                raise ValueError("Photo absente ou en double dans la sauvegarde.")
            ids.add(photo_id)
            photos.add(path)
    if photos != {name for name in files if name.startswith("photos/")}:
        raise ValueError("La sauvegarde contient des photos non référencées.")


def _validate_prefs(data):
    if not isinstance(data, dict):
        raise ValueError("Réglages invalides.")
    for key in ("hidden", "hidden_catalogues", "favorites", "recent"):
        if key in data and (not isinstance(data[key], list) or any(not isinstance(v, str) for v in data[key])):
            raise ValueError("Filtres ou favoris invalides.")
    prices = data.get("prices", {})
    if not isinstance(prices, dict) or any(not _price(v) for v in prices.values()):
        raise ValueError("Prix personnalisés invalides.")
    if not isinstance(data.get("custom", []), list):
        raise ValueError("Articles personnalisés invalides.")
    for item in data.get("custom", []):
        if (not isinstance(item, dict) or not isinstance(item.get("key"), str)
                or not item["key"].startswith("PERSO:") or not _price(item.get("price"))
                or any(not isinstance(item.get(k), str) or not item[k].strip() for k in ("name", "category"))
                or ("catalogue" in item and not isinstance(item["catalogue"], str))):
            raise ValueError("Article personnalisé invalide.")
    if "catalogue_items" in data:
        if not isinstance(data["catalogue_items"], list):
            raise ValueError("Catalogue local invalide.")
        keys = set()
        for item in data["catalogue_items"]:
            if (not isinstance(item, dict) or not _price(item.get("Prix_Excel"))
                    or any(not isinstance(item.get(k), str) for k in ("Cle", "Nom_Article", "Catalogue", "Categorie"))
                    or not item["Cle"].startswith(("XL:", "CAT:")) or item["Cle"] in keys
                    or not item["Nom_Article"].strip() or not item["Categorie"].strip()):
                raise ValueError("Article du catalogue local invalide.")
            keys.add(item["Cle"])


def create_backup(root):
    root = Path(root)
    files = {name: _target(root, name).read_bytes() for name in ROOT_FILES if _target(root, name).exists()}
    files.setdefault(ORDERS, b'{"orders":{},"current":null}')
    files.setdefault(PREFS, b"{}")
    if sum(name in files for name in CATALOGUES) > 1:
        raise ValueError("Plusieurs fichiers catalogue locaux : remplacez le catalogue avant la sauvegarde.")
    orders = _json(files[ORDERS])
    for order_id, order in orders["orders"].items():
        _component(order_id)
        for photo in order.get("photos", []):
            filename = _component(photo["file"])
            relative = f"photos/{order_id}/{filename}"
            files[relative] = _target(root, relative).read_bytes()
    _validate_orders(orders, files)
    _validate_prefs(_json(files[PREFS]))
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
        raise ValueError("Sauvegarde trop volumineuse (maximum 512 Mo ou 5 000 fichiers).")
    manifest = {"format": "prise-commande", "version": 1, "created": datetime.now().isoformat(timespec="seconds"),
                "files": {name: {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                          for name, data in files.items()}}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        for name, data in files.items():
            archive.writestr(name, data)
    result = buffer.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError("Fichier de sauvegarde trop volumineux (maximum 512 Mo).")
    return result


def inspect_backup(data, validate_catalogue):
    """Validate the complete archive, including hashes and catalogue parsing."""
    try:
        if len(data) > MAX_BYTES:
            raise ValueError("Fichier trop volumineux (maximum 512 Mo).")
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (len(entries) > MAX_FILES + 1 or len(set(name.casefold() for name in names)) != len(names)
                    or sum(entry.file_size for entry in entries) > MAX_BYTES
                    or any(entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16) for entry in entries)):
                raise ValueError("Archive trop volumineuse, chiffrée ou contenant des doublons/liens.")
            manifest = _json(archive.read("manifest.json"))
            if (not isinstance(manifest, dict) or manifest.get("format") != "prise-commande"
                    or type(manifest.get("version")) is not int or manifest["version"] != 1
                    or not isinstance(manifest.get("files"), dict)):
                raise ValueError("Format de sauvegarde inconnu.")
            _date(manifest.get("created"))
            if set(names) != {"manifest.json", *manifest["files"]}:
                raise ValueError("Liste des fichiers incomplète.")
            files = {}
            for name, metadata in manifest["files"].items():
                parts = PurePosixPath(name).parts
                if name not in ROOT_FILES and not (len(parts) == 3 and parts[0] == "photos"):
                    raise ValueError("Fichier inattendu dans la sauvegarde.")
                if PurePosixPath(name).is_absolute() or any(_component(part) != part for part in parts):
                    raise ValueError("Chemin interdit.")
                payload = archive.read(name)
                if (not isinstance(metadata, dict) or metadata.get("size") != len(payload)
                        or metadata.get("sha256") != hashlib.sha256(payload).hexdigest()):
                    raise ValueError("Un fichier est endommagé (empreinte incorrecte).")
                files[name] = payload
        orders = _json(files[ORDERS])
        _validate_orders(orders, files)
        _validate_prefs(_json(files[PREFS]))
        catalogues = [name for name in CATALOGUES if name in files]
        if len(catalogues) > 1:
            raise ValueError("Plusieurs fichiers catalogue dans la sauvegarde.")
        for name in catalogues:
            try:
                validate_catalogue(files[name], Path(name).suffix)
            except Exception as err:
                raise ValueError(f"Catalogue illisible : {err}") from err
        return Snapshot(files, orders, manifest["created"])
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, UnicodeError, zipfile.BadZipFile,
            RuntimeError, NotImplementedError) as err:
        raise ValueError(f"Sauvegarde invalide : {err}") from err


def restore_backup(root, snapshot):
    """Merge imported orders, replace catalogue/settings, keep a recovery ZIP.

    Files are staged first. An I/O failure rolls back touched files; the complete
    pre-restore recovery ZIP is retained even if rollback itself cannot finish.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    recovery_data = create_backup(root)
    existing = _json(_target(root, ORDERS).read_bytes()) if _target(root, ORDERS).exists() else {"orders": {}, "current": None}
    merged = copy.deepcopy(existing)
    mapping, updates = {}, {}
    reserved_ids = {key.casefold() for key in merged["orders"]}
    for order_id, order in snapshot.orders["orders"].items():
        new_id = order_id
        while new_id.casefold() in reserved_ids or _target(root, f"photos/{new_id}").exists():
            new_id = uuid.uuid4().hex[:8]
        reserved_ids.add(new_id.casefold())
        mapping[order_id] = new_id
        merged["orders"][new_id] = copy.deepcopy(order)
        for photo in order.get("photos", []):
            updates[f"photos/{new_id}/{photo['file']}"] = snapshot.files[f"photos/{order_id}/{photo['file']}"]
    if merged.get("current") not in merged["orders"]:
        merged["current"] = mapping.get(snapshot.orders.get("current"))
    updates.update({name: data for name, data in snapshot.files.items() if name in (PREFS, *CATALOGUES)})
    updates[ORDERS] = json.dumps(merged, ensure_ascii=False, indent=1).encode("utf-8")
    originals = {name: _target(root, name).read_bytes() if _target(root, name).exists() else None for name in ROOT_FILES}
    recovery = _target(root, f"sauvegardes/avant-restauration-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.zip")
    recovery.parent.mkdir(parents=True, exist_ok=True)
    recovery.write_bytes(recovery_data)
    touched = []
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=root) as directory:
        stage = Path(directory)
        staged = {}
        for index, (name, data) in enumerate(updates.items()):
            _target(root, name)  # validate even if a directory is a pre-existing link
            path = stage / str(index)
            path.write_bytes(data)
            staged[name] = path
        try:
            for name, path in staged.items():
                target = _target(root, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(path, target)
                touched.append(name)
            if any(name in snapshot.files for name in CATALOGUES):
                for name in CATALOGUES:
                    if name not in snapshot.files and _target(root, name).exists():
                        _target(root, name).unlink()
                        touched.append(name)
        except OSError as err:
            try:
                for index, name in enumerate(reversed(touched)):
                    target = _target(root, name)
                    original = originals.get(name)
                    if original is None:
                        target.unlink(missing_ok=True)
                    else:
                        rollback = stage / f"rollback-{index}"
                        rollback.write_bytes(original)
                        os.replace(rollback, target)
            except OSError as rollback_error:
                raise OSError(f"Restauration interrompue. Copie de secours : {recovery.name}. {rollback_error}") from err
            raise OSError(f"Restauration annulée, données précédentes conservées. {err}") from err
    return recovery
