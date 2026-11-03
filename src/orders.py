# Calculs et texte d'une commande (total, e-mail, duplication).

import copy
import shutil
import uuid
from datetime import datetime
from pathlib import Path

if __package__:
    from .text import fmt_eur
    from .storage import photo_path, photos_dir
else:
    from text import fmt_eur
    from storage import photo_path, photos_dir


def order_total(order):
    return sum(v["Prix"] * v["quantite"] for v in order["items"].values())


def order_count(order):
    return sum(v["quantite"] for v in order["items"].values())


def order_email_text(order):
    text = f"Bonjour,\n\nVoici le détail de la commande « {order['name']} » :\n\n"
    if order.get("notes"):
        text += f"Remarques : {order['notes']}\n\n"
    for item in order["items"].values():
        text += f"- {item['quantite']}x {item['Nom']} ({fmt_eur(item['Prix'])}/u) = {fmt_eur(item['Prix'] * item['quantite'])}\n"
        if item.get("note"):
            text += f"  Remarque : {item['note']}\n"
    return text + f"\nTOTAL : {fmt_eur(order_total(order))}\n\nMerci."


def duplicate_order(order_id, order, name=None, existing_ids=()):
    """Independent draft, including independent photo files and labels."""
    new_id = uuid.uuid4().hex[:8]
    while new_id in existing_ids or photos_dir(new_id).exists():
        new_id = uuid.uuid4().hex[:8]
    duplicate = copy.deepcopy(order)
    duplicate.update(name=(name or "").strip() or f"{order['name']} — copie",
                     created=datetime.now().isoformat(timespec="minutes"), photos=[])
    duplicate.pop("archived", None)
    target = photos_dir(new_id)
    try:
        for photo in order.get("photos", []):
            photo_id = uuid.uuid4().hex[:8]
            filename = photo_id + Path(photo["file"]).suffix
            target.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(photo_path(order_id, photo), target / filename)
            duplicate["photos"].append({**photo, "id": photo_id, "file": filename})
    except OSError:
        # Only files just created for this new, generated ID are removed.
        for path in target.glob("*"):
            path.unlink()
        if target.exists():
            target.rmdir()
        raise
    return new_id, duplicate
