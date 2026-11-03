# Photos d'une commande : noms d'export, résumé, archive ZIP.

import io
import os
import re
import zipfile
from datetime import datetime

if __package__:
    from .text import fmt_eur
    from .storage import photo_path
    from .orders import order_total
else:
    from text import fmt_eur
    from storage import photo_path
    from orders import order_total


def safe_filename(text, fallback="photo"):
    """Texte utilisable comme nom de fichier sous Windows et Android."""
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(text))
    text = " ".join(text.split()).strip(" .")
    return text[:60] or fallback


def photo_export_names(order):
    """Noms des photos exportées, numérotés dans l'ordre : « 01 - Ancien serveur.jpg »."""
    names = []
    for i, photo in enumerate(order.get("photos", []), 1):
        ext = os.path.splitext(photo["file"])[1].lower() or ".jpg"
        names.append(f"{i:02d} - {safe_filename(photo['label'])}{ext}")
    return names


def photos_summary(order, names):
    """Texte joint à l'export : commande, liste des photos avec leur libellé, articles."""
    lines = [f"Commande : {order['name']}",
             f"Exporté le {datetime.now():%d/%m/%Y à %H:%M}", "", "Photos :"]
    for photo, name in zip(order.get("photos", []), names):
        added = datetime.fromisoformat(photo["added"]).strftime("%d/%m/%Y %H:%M")
        lines.append(f"- {name} : {photo['label']} (prise le {added})")
    if order.get("notes"):
        lines += ["", f"Remarques : {order['notes']}"]
    if order["items"]:
        lines += ["", "Articles de la commande :"]
        for item in order["items"].values():
            lines.append(f"- {item['quantite']}x {item['Nom']} ({fmt_eur(item['Prix'])}/u)")
            if item.get("note"):
                lines.append(f"  Remarque : {item['note']}")
        lines.append(f"TOTAL : {fmt_eur(order_total(order))}")
    return lines


def build_photos_zip(order_id, order):
    """ZIP en mémoire : les photos nommées par leur libellé + « photos.txt »."""
    names = photo_export_names(order)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for photo, name in zip(order["photos"], names):
            # JPEG déjà compressé : stocké tel quel (plus rapide, même taille)
            archive.write(photo_path(order_id, photo), arcname=name, compress_type=zipfile.ZIP_STORED)
        # \r\n : lisible correctement dans le Bloc-notes de Windows
        archive.writestr("photos.txt", "\r\n".join(photos_summary(order, names)))
    return buffer.getvalue()
