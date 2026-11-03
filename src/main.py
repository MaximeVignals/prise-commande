import asyncio
import io
import json
import os
import re
import shutil
import unicodedata
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

import flet as ft
from openpyxl import load_workbook

try:
    # Appareil photo intégré (Android) : extension officielle flet-camera.
    # Absente (ex. « flet run » sur PC sans l'extension) → seul l'import de photos est proposé.
    import flet_camera as fc
except ImportError:
    fc = None

CATALOGUE_FILENAME = "catalogue materiel.xlsx"            # vrai catalogue : privé, jamais dans le dépôt
SAMPLE_CATALOGUE_FILENAME = "catalogue exemple.xlsx"      # catalogue fictif fourni avec le code
RULES_FILENAME = "regles_catalogue.json"                   # règles propres au vrai catalogue : privé
SAMPLE_RULES_FILENAME = "regles_catalogue.exemple.json"   # règles d'exemple fournies avec le code
ORDERS_FILENAME = "commandes.json"
PREFS_FILENAME = "catalogue_perso.json"  # articles masqués, prix modifiés, articles ajoutés

# Les règles propres au catalogue (catégories renommées, sections retirées, articles masqués
# par défaut…) sont lues dans regles_catalogue.json, à côté du catalogue. Voir rules().

# Préfixes des clés d'articles (identifiant stable, indépendant de la position dans l'Excel)
KEY_EXCEL = "XL:"
KEY_PERSO = "PERSO:"

# --- FONCTIONS DE NETTOYAGE ET UTILITAIRES ---


def assets_dir():
    # Dans l'APK / l'exe, Flet fournit le dossier assets via FLET_ASSETS_DIR.
    # En développement (flet run), on retombe sur src/assets/ à côté de ce fichier.
    return Path(os.getenv("FLET_ASSETS_DIR") or str(Path(__file__).parent / "assets"))


def _asset(real_name, sample_name):
    """Le fichier réel s'il est présent (construction sur le PC), sinon l'exemple fourni avec le code."""
    real = assets_dir() / real_name
    return real if real.exists() else assets_dir() / sample_name


def _as_list(value):
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value] if isinstance(value, list) else []


_RULES_CACHE = {}


def rules():
    """Règles du catalogue (regles_catalogue.json, sinon l'exemple). Clés :
    - textes_retires      : textes supprimés des titres de catégorie ;
    - categories_renommees: [{"egal" ou "contient": texte(s), "nom": nouveau nom}], dans l'ordre ;
    - mots_en_majuscules  : mots gardés en majuscules dans les noms de catégorie ;
    - sections_exclues    : un titre en GRAS contenant un de ces mots fait ignorer toute la section ;
    - masques_par_defaut  : articles contenant un de ces mots masqués au premier lancement
                            (réactivables dans « Gérer les articles »).
    Un fichier absent ou illisible donne des règles vides : l'application démarre quand même."""
    if "r" in _RULES_CACHE:
        return _RULES_CACHE["r"]
    data = {}
    path = _asset(RULES_FILENAME, SAMPLE_RULES_FILENAME)
    try:
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError) as err:
        print(f"[règles] {path.name} illisible ou absent : {err}")
    renames = []
    for r in data.get("categories_renommees", []) if isinstance(data.get("categories_renommees"), list) else []:
        if isinstance(r, dict) and r.get("nom") and ("egal" in r or "contient" in r):
            renames.append({"egal": [t.upper() for t in _as_list(r.get("egal"))],
                            "contient": [t.upper() for t in _as_list(r.get("contient"))],
                            "nom": str(r["nom"])})
    result = {
        "textes_retires": _as_list(data.get("textes_retires")),
        "categories_renommees": renames,
        "mots_en_majuscules": {w.upper() for w in _as_list(data.get("mots_en_majuscules"))},
        "sections_exclues": tuple(fold(w) for w in _as_list(data.get("sections_exclues"))),
        "masques_par_defaut": tuple(fold(w) for w in _as_list(data.get("masques_par_defaut"))),
    }
    _RULES_CACHE["r"] = result
    return result


def clean_category_name(raw_name):
    r = rules()
    name = raw_name
    for text in r["textes_retires"]:
        name = name.replace(text, "")
    name = name.strip()
    upper = name.upper()
    for rename in r["categories_renommees"]:
        if upper in rename["egal"] or any(t in upper for t in rename["contient"]):
            return rename["nom"]

    words = name.split()
    cleaned_words = []
    for w in words:
        if w.upper() in r["mots_en_majuscules"]:
            cleaned_words.append(w.upper())
        elif len(w) > 2 and w.isupper():
            cleaned_words.append(w.capitalize())
        else:
            cleaned_words.append(w if w.islower() else w.capitalize())

    return " ".join(cleaned_words).replace(" / ", " - ")


def get_category_icon(category_name):
    cat_lower = str(category_name).lower()
    if any(word in cat_lower for word in ["écran", "ecran", "moniteur"]): return "🖥️"
    if any(word in cat_lower for word in ["unité", "pc", "ordinateur", "portable"]): return "💻"
    if any(word in cat_lower for word in ["serveur", "baie", "nas"]): return "🗄️"
    if "clavier" in cat_lower or "souris" in cat_lower: return "⌨️"
    if any(word in cat_lower for word in ["imprimante", "scanner", "copieur"]): return "🖨️"
    if any(word in cat_lower for word in ["réseau", "onduleur", "switch"]): return "🔌"
    if any(word in cat_lower for word in ["tablette", "smartphone"]): return "📱"
    if any(word in cat_lower for word in ["radio", "imagerie", "capteur"]): return "📷"
    if any(word in cat_lower for word in ["3d", "résine"]): return "🧊"
    if any(word in cat_lower for word in ["papeterie", "chèques"]): return "📄"
    return "📦"


def _is_empty(value):
    return value is None or (isinstance(value, str) and value.strip() == "")


def norm_text(value):
    """Texte sur une seule ligne, espaces multiples réduits (certaines cellules contiennent des retours à la ligne)."""
    return " ".join(str(value).split())


def fold(text):
    """Minuscules sans accents, pour comparer des noms sans se soucier de la saisie."""
    text = unicodedata.normalize("NFKD", str(text).lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _contains_any(text, words):
    folded = fold(text)
    return any(w in folded for w in words)


def catalogue_path():
    # Vrai catalogue s'il a été copié dans assets (construction), sinon le catalogue d'exemple.
    return _asset(CATALOGUE_FILENAME, SAMPLE_CATALOGUE_FILENAME)


def load_catalogue():
    """Lit la 1re feuille de l'Excel (A = nom, B = tarif neuf, C = tarif occasion).
    Retourne une liste de dicts : Cle, Nom_Article, Categorie, Prix_Excel.

    Règles de lecture :
    - ligne en GRAS sans prix          → titre de catégorie ;
    - ligne avec un prix neuf          → article (en gras ou non) ;
    - ligne NON grasse sans prix       → détail d'un pack, option ou remarque : ignorée ;
    - titre contenant un mot de « sections_exclues » (règles) → toute la section est ignorée.
    """
    file_path = catalogue_path()
    if not file_path.exists():
        return []

    # Mode complet (pas read_only) : il faut la mise en forme (gras) pour reconnaître les catégories.
    wb = load_workbook(file_path, data_only=True)
    try:
        ws = wb.worksheets[0]
        items = []
        used_keys = set()
        current_category = "Général"
        in_excluded_section = False

        for cells in ws.iter_rows(min_col=1, max_col=3):
            name, raw_neuf, raw_occ = (c.value for c in cells)

            if str(raw_neuf).strip().upper() == "TARIF NEUF": continue
            if _is_empty(name): continue

            name = norm_text(name)
            is_bold = bool(cells[0].font and cells[0].font.b)
            prix_neuf = _to_price(raw_neuf)

            if is_bold and prix_neuf is None:
                # Titre : catégorie, ou section retirée
                in_excluded_section = _contains_any(name, rules()["sections_exclues"])
                if in_excluded_section:
                    continue
                if _is_empty(raw_neuf) and _is_empty(raw_occ):
                    current_category = clean_category_name(name)
                else:
                    print(f"[catalogue] Titre ignoré (texte dans les colonnes de prix) : "
                          f"{name!r} | neuf={raw_neuf!r} | occasion={raw_occ!r}")
                continue

            if in_excluded_section:
                continue

            if prix_neuf is None:
                if not (_is_empty(raw_neuf) and _is_empty(raw_occ)):
                    # Ligne d'article sans prix neuf lisible : on la signale au lieu de l'ignorer en silence
                    print(f"[catalogue] Ligne ignorée (prix neuf illisible) : "
                          f"{name!r} | neuf={raw_neuf!r} | occasion={raw_occ!r}")
                continue

            # Clé = nom de l'article : ne change pas si on ajoute / supprime des lignes dans l'Excel
            key = KEY_EXCEL + name
            n = 2
            while key in used_keys:  # deux articles portant le même nom
                key = f"{KEY_EXCEL}{name} ({n})"
                n += 1
            used_keys.add(key)

            items.append({
                "Cle": key,
                "Nom_Article": name,
                "Categorie": current_category,
                "Prix_Excel": prix_neuf,
            })
        return items
    finally:
        wb.close()


def _to_price(value):
    """Convertit une cellule (ou une saisie) en prix (float) ou None.
    Accepte les nombres, mais aussi le texte : '4 990,00 €', '4990.5', '1.234,56', '1.234' (= 1 234)."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
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
        return float(s)
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
    if order["items"]:
        lines += ["", "Articles de la commande :"]
        for item in order["items"].values():
            lines.append(f"- {item['quantite']}x {item['Nom']} ({fmt_eur(item['Prix'])}/u)")
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
            except (KeyError, TypeError, ValueError):
                continue
            if clean["quantite"] > 0:
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
    return orders, data.get("current"), None


def save_orders(orders, current_id):
    write_json(orders_path(), {"orders": orders, "current": current_id})


def migrate_cart_keys(orders):
    """Les anciennes versions repéraient les lignes de panier par leur position dans l'Excel (ART_0001…),
    qui change dès qu'on ajoute une ligne au fichier. On les repère désormais par le nom de l'article.
    Retourne True si quelque chose a été converti."""
    changed = False
    for order in orders.values():
        if all(k.startswith((KEY_EXCEL, KEY_PERSO)) for k in order["items"]):
            continue
        changed = True
        new_items = {}
        for key, line in order["items"].items():
            new_key = key if key.startswith((KEY_EXCEL, KEY_PERSO)) else KEY_EXCEL + line["Nom"]
            if new_key in new_items:
                existing = new_items[new_key]
                if abs(existing["Prix"] - line["Prix"]) < 0.005:
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
    """Réglages du catalogue : {"hidden": set de clés, "prices": {clé: prix}, "custom": [articles ajoutés]}.
    Retourne (réglages, avertissement)."""
    path = prefs_path()
    data, warning = read_json(path)
    if data is not None and not isinstance(data, dict):
        data, warning = None, _set_aside(path, "format inattendu")

    if data is None:
        # Premier lancement : articles listés dans « masques_par_defaut » (règles) masqués par défaut
        hidden = {it["Cle"] for it in excel_items if _contains_any(it["Nom_Article"], rules()["masques_par_defaut"])}
        return {"hidden": hidden, "prices": {}, "custom": []}, warning

    hidden = {str(k) for k in data.get("hidden", [])} if isinstance(data.get("hidden"), list) else set()
    prices = {}
    if isinstance(data.get("prices"), dict):
        for k, v in data["prices"].items():
            p = _to_price(v)
            if p is not None:
                prices[str(k)] = p
    custom = []
    for c in data.get("custom", []) if isinstance(data.get("custom"), list) else []:
        try:
            article = {"key": str(c["key"]), "name": norm_text(c["name"]),
                       "category": norm_text(c["category"]), "price": float(c["price"])}
        except (KeyError, TypeError, ValueError):
            continue
        if article["key"].startswith(KEY_PERSO) and article["name"] and article["category"]:
            custom.append(article)
    return {"hidden": hidden, "prices": prices, "custom": custom}, None


def save_prefs(prefs):
    write_json(prefs_path(), {
        "hidden": sorted(prefs["hidden"]),
        "prices": prefs["prices"],
        "custom": prefs["custom"],
    })


def build_catalogue(excel_items, prefs):
    """Catalogue utilisé par l'app : articles Excel + articles ajoutés, avec prix modifiés et visibilité."""
    entries = []
    for it in excel_items:
        key = it["Cle"]
        entries.append({
            "Cle": key,
            "Nom_Article": it["Nom_Article"],
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


def default_order_name():
    return f"Commande du {datetime.now().strftime('%d/%m %H:%M')}"


def order_total(order):
    return sum(v["Prix"] * v["quantite"] for v in order["items"].values())


def order_count(order):
    return sum(v["quantite"] for v in order["items"].values())


# --- APPLICATION PRINCIPALE FLET ---


def main(page: ft.Page):
    page.title = "Prise de Commande"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 10

    excel_items = load_catalogue()
    clipboard = ft.Clipboard()  # service : on garde une référence

    if not excel_items:
        page.add(ft.SafeArea(content=ft.Text(
            f"Fichier catalogue introuvable ou vide.\n({catalogue_path()})",
            color=ft.Colors.RED,
        )))
        return

    # Défini en premier : utilisé par les sauvegardes dès le démarrage
    def show_snack(message):
        page.show_dialog(ft.SnackBar(ft.Text(message), duration=ft.Duration(milliseconds=2000)))

    def refresh():
        """Envoie toutes les modifications à l'écran.

        Flet 1.0 rafraîchit l'écran tout seul à la fin d'un clic, SAUF si quelque chose a déjà
        été rafraîchi pendant ce clic. Or afficher un message (SnackBar) ou une boîte de dialogue
        le fait : le message apparaissait, mais le panier, le total, le menu… restaient figés.
        On appelle donc refresh() à la fin de chaque action qui affiche un message ou une boîte.
        """
        page.update()

    startup_warnings = []

    # --- ÉTAT : plusieurs commandes nommées, une seule active à la fois ---
    orders, current_id, warning = load_orders()
    if warning:
        startup_warnings.append(warning)
    migrated = migrate_cart_keys(orders)
    state = {"current": current_id}

    # --- RÉGLAGES DU CATALOGUE (articles affichés, prix, articles ajoutés) ---
    prefs, warning = load_prefs(excel_items)
    if warning:
        startup_warnings.append(warning)
    cat = {"all": build_catalogue(excel_items, prefs)}

    def rebuild_catalogue():
        cat["all"] = build_catalogue(excel_items, prefs)

    def entry_by_key(key):
        return next((e for e in cat["all"] if e["Cle"] == key), None)

    def visible_entries():
        return [e for e in cat["all"] if e["Visible"]]

    def new_order(name=None):
        order_id = uuid.uuid4().hex[:8]
        orders[order_id] = {
            "name": (name or "").strip() or default_order_name(),
            "created": datetime.now().isoformat(timespec="minutes"),
            "items": {},
            "photos": [],
        }
        state["current"] = order_id
        return order_id

    # Aucune création automatique : s'il n'y a pas encore de commande,
    # l'écran d'aide « Créer une commande » s'affiche à la place du catalogue.
    if state["current"] not in orders:
        state["current"] = list(orders)[-1] if orders else None  # la plus récente

    def current_order():
        return orders[state["current"]]

    def cart():
        return current_order()["items"]

    def persist():
        try:
            save_orders(orders, state["current"])
        except OSError as err:
            show_snack(f"⚠️ Sauvegarde impossible : {err}")

    def persist_prefs():
        try:
            save_prefs(prefs)
        except OSError as err:
            show_snack(f"⚠️ Sauvegarde des réglages impossible : {err}")

    # --- COMPOSANTS UI ---
    async def on_catalogue_filter(e=None):
        render_catalogue()
        refresh()
        await catalogue_listview.scroll_to(offset=0)  # résultats affichés depuis le début

    search_input = ft.TextField(
        label="Rechercher",
        hint_text="ex. ecran dell 24",
        prefix_icon=ft.Icons.SEARCH,
        on_change=on_catalogue_filter,
        expand=3,
    )

    category_dropdown = ft.Dropdown(
        label="Catégorie",
        options=[],
        value="Toutes",
        on_select=on_catalogue_filter,
        expand=2,
    )

    catalogue_listview = ft.ListView(expand=True, spacing=10, padding=10)
    cart_listview = ft.ListView(expand=True, spacing=10, padding=10)
    total_text = ft.Text(f"Total : {fmt_eur(0)}", size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_900)

    # Titre de la barre du haut = nom de la commande active
    appbar_title = ft.Text("", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           weight=ft.FontWeight.W_600)
    # Menu latéral (comme la liste des conversations de Claude) : rempli par render_orders()
    drawer = ft.NavigationDrawer(controls=[], selected_index=-1, bgcolor=ft.Colors.GREY_50)

    # --- LOGIQUE ---

    def go_to_tab(index):
        tabs.selected_index = index

    def add_to_cart(item, qty):
        try:
            qty = int(qty)
        except (TypeError, ValueError):
            show_snack("Quantité invalide.")
            return
        if qty <= 0:
            show_snack("Quantité invalide.")
            return

        items = cart()
        if item["Cle"] in items:
            items[item["Cle"]]["quantite"] += qty
        else:
            items[item["Cle"]] = {
                "Nom": item["Nom_Article"],
                "Prix": item["Prix_Unitaire"],
                "quantite": qty,
            }
        persist()
        render_all()
        show_snack(f"✅ Ajouté au panier (x{qty})")
        refresh()

    def change_qty_field(field, delta):
        try:
            current = int(field.value)
        except (TypeError, ValueError):
            current = 1
        field.value = str(max(1, current + delta))

    def update_cart_qty(id_art, delta):
        items = cart()
        if id_art not in items:
            return
        if items[id_art]["quantite"] + delta <= 0:
            remove_cart_line(id_art)  # « − » sur une quantité de 1 : retire la ligne (annulable)
            return
        items[id_art]["quantite"] += delta
        persist()
        render_all()
        refresh()

    def remove_cart_line(id_art):
        """Retire une ligne du panier, avec « Annuler » dans le message pendant 8 secondes."""
        order_id = state["current"]
        items = cart()
        if id_art not in items:
            return
        position = list(items).index(id_art)
        line = items.pop(id_art)
        persist()
        render_all()

        def undo(e):
            if order_id not in orders or id_art in orders[order_id]["items"]:
                return
            restored = list(orders[order_id]["items"].items())
            restored.insert(position, (id_art, line))
            orders[order_id]["items"].clear()
            orders[order_id]["items"].update(restored)
            persist()
            render_all()
            refresh()

        page.show_dialog(ft.SnackBar(
            ft.Text("🗑️ Ligne retirée du panier."),
            action="Annuler",
            on_action=undo,
            persist=False,
            duration=ft.Duration(seconds=8),  # le temps de toucher « Annuler »
        ))
        refresh()

    def set_cart_qty(id_art, field, subtotal_text, final):
        """Quantité tapée au clavier. Enregistrée à chaque chiffre ; à la sortie du champ,
        une saisie vide ou à 0 est annulée (pour retirer une ligne : la corbeille)."""
        items = cart()
        if id_art not in items:
            return
        try:
            qty = int(field.value)
        except (TypeError, ValueError):
            qty = 0
        if qty > 0:
            if qty != items[id_art]["quantite"]:
                items[id_art]["quantite"] = qty
                persist()
                subtotal_text.value = fmt_eur(items[id_art]["Prix"] * qty)
                update_cart_summary()
                render_orders()
            if final:
                field.value = str(qty)
        elif final:
            field.value = str(items[id_art]["quantite"])
            show_snack("Quantité invalide. Pour retirer la ligne, utilisez la corbeille.")
        refresh()

    def clear_cart(e):
        order = current_order()
        if not order["items"]:
            show_snack("Le panier est déjà vide.")
            refresh()
            return

        def confirm(e):
            page.pop_dialog()
            if not order["items"]:  # double appui
                return
            order["items"].clear()
            persist()
            render_all()
            show_snack("🗑️ Panier vidé.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Vider le panier ?"),
            content=ft.Text(
                f"Les {order_count(order)} article(s) de « {order['name']} » "
                f"({fmt_eur(order_total(order))}) seront retirés."
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.Button(content="Vider", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.RED, color=ft.Colors.WHITE)),
            ],
        ))

    async def copy_email_text(e):
        order = current_order()
        if not order["items"]:
            show_snack("Le panier est vide.")
            return

        texte_email = f"Bonjour,\n\nVoici le détail de la commande « {order['name']} » :\n\n"
        for item in order["items"].values():
            sous_total = item["Prix"] * item["quantite"]
            texte_email += f"- {item['quantite']}x {item['Nom']} ({fmt_eur(item['Prix'])}/u) = {fmt_eur(sous_total)}\n"
        texte_email += f"\nTOTAL : {fmt_eur(order_total(order))}\n\nMerci."

        await clipboard.set(texte_email)
        show_snack("📋 Texte copié dans le presse-papiers !")

    # --- GESTION DES COMMANDES ---

    async def open_drawer(e=None):
        await page.show_drawer()

    async def close_drawer():
        await page.close_drawer()

    async def select_order(order_id):
        if order_id not in orders:
            return
        state["current"] = order_id
        persist()
        render_all()
        await close_drawer()
        show_snack(f"Commande active : {orders[order_id]['name']}")
        refresh()

    def ask_name(title, initial, on_ok):
        """Petite boîte de dialogue avec un champ texte (création / renommage)."""
        name_field = ft.TextField(
            value=initial,
            label="Nom de la commande",
            hint_text="ex. Cabinet Dupont – salle 2",
            autofocus=True,
            capitalization=ft.TextCapitalization.SENTENCES,
        )

        def validate(e=None):
            page.pop_dialog()
            on_ok(name_field.value)
            refresh()

        name_field.on_submit = validate
        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=name_field,
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.Button(content="Valider", on_click=validate),
            ],
        ))

    async def create_order_dialog(e=None):
        await close_drawer()

        def done(name):
            new_order(name)
            persist()
            render_all()
            go_to_tab(0)  # retour au catalogue pour remplir la nouvelle commande
            show_snack(f"🆕 Nouvelle commande : {current_order()['name']}")

        ask_name("Nouvelle commande", default_order_name(), done)

    async def rename_order_dialog(order_id):
        await close_drawer()

        def done(name):
            name = name.strip()
            if name and order_id in orders:
                orders[order_id]["name"] = name
                persist()
                render_all()

        ask_name("Renommer la commande", orders[order_id]["name"], done)

    async def delete_order_dialog(order_id):
        await close_drawer()
        order = orders[order_id]

        def confirm(e):
            page.pop_dialog()
            if order_id not in orders:  # double appui sur « Supprimer »
                return
            del orders[order_id]
            shutil.rmtree(photos_dir(order_id), ignore_errors=True)  # ses photos aussi
            if state["current"] == order_id:
                # la plus récente restante, ou aucune → écran d'aide
                state["current"] = list(orders)[-1] if orders else None
            persist()
            render_all()
            show_snack(f"🗑️ « {order['name']} » supprimée.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Supprimer la commande ?"),
            content=ft.Text(
                f"« {order['name']} » ({order_count(order)} article(s), "
                f"{fmt_eur(order_total(order))}) sera définitivement supprimée."
                + (f"\nSes {len(order.get('photos', []))} photo(s) aussi."
                   if order.get("photos") else "")
            ),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.Button(
                    content="Supprimer",
                    on_click=confirm,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.RED, color=ft.Colors.WHITE),
                ),
            ],
        ))

    # --- RENDU CATALOGUE ---
    def render_catalogue():
        catalogue_listview.controls.clear()
        shown = visible_entries()
        categories = categories_of(shown)

        # Filtre : seules les catégories qui ont au moins un article affiché
        category_dropdown.options = [ft.DropdownOption(key=c, text=c) for c in ["Toutes"] + sorted(categories)]
        if category_dropdown.value not in categories:
            category_dropdown.value = "Toutes"

        search_val = search_input.value or ""
        cat_val = category_dropdown.value

        filtered = [
            it for it in shown
            if matches_search(it["Nom_Article"], search_val)
            and (cat_val == "Toutes" or it["Categorie"] == cat_val)
        ]

        if not shown:
            catalogue_listview.controls.append(ft.Text(
                "Aucun article affiché.\nCochez des articles dans ☰ › Gérer les articles.",
                italic=True, color=ft.Colors.GREY_700,
            ))

        for categorie in categories:
            group = [it for it in filtered if it["Categorie"] == categorie]
            if not group:
                continue

            # En-tête de catégorie
            catalogue_listview.controls.append(
                ft.Container(
                    content=ft.Text(f"{get_category_icon(categorie)} {categorie}", size=18, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.BLUE_50,
                    padding=10,
                    border_radius=5,
                    margin=ft.Margin.only(top=10),
                )
            )

            # Articles
            for current_item in group:
                qty_field = ft.TextField(
                    value="1", width=50, text_align=ft.TextAlign.CENTER,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    input_filter=ft.NumbersOnlyInputFilter(),
                    dense=True,
                )

                # Flèches ▼ / ▲ pour ajuster la quantité à ajouter (minimum 1)
                btn_down = ft.IconButton(
                    icon=ft.Icons.KEYBOARD_ARROW_DOWN,
                    tooltip="Diminuer",
                    visual_density=ft.VisualDensity.COMPACT,
                    on_click=lambda e, q=qty_field: change_qty_field(q, -1),
                )
                btn_up = ft.IconButton(
                    icon=ft.Icons.KEYBOARD_ARROW_UP,
                    tooltip="Augmenter",
                    visual_density=ft.VisualDensity.COMPACT,
                    on_click=lambda e, q=qty_field: change_qty_field(q, 1),
                )

                add_btn = ft.IconButton(
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    icon_color=ft.Colors.WHITE,
                    bgcolor=ft.Colors.BLUE,
                    on_click=lambda e, item=current_item, q=qty_field: add_to_cart(item, q.value),
                )

                catalogue_listview.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text(current_item["Nom_Article"], weight=ft.FontWeight.W_500),
                            ft.Row([
                                ft.Text(fmt_eur(current_item['Prix_Unitaire']), color=ft.Colors.GREEN_700, weight=ft.FontWeight.BOLD),
                                ft.Row(
                                    [btn_down, qty_field, btn_up, add_btn],
                                    alignment=ft.MainAxisAlignment.END,
                                    spacing=2,
                                ),
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ]),
                        padding=10,
                        border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_300)),
                    )
                )
        # Plus besoin de page.update() : Flet 1.0 met à jour automatiquement
        # après chaque gestionnaire d'événement et après main().

    # --- RENDU PANIER ---
    def render_cart():
        cart_listview.controls.clear()
        items = cart()

        if not items:
            cart_listview.controls.append(ft.Text("Le panier est vide.", italic=True))
        else:
            for id_art, item in items.items():
                sous_total = item["Prix"] * item["quantite"]
                subtotal_text = ft.Text(fmt_eur(sous_total), weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.GREEN_700)

                # Quantité modifiable au clavier, ou avec − / +
                qty_field = ft.TextField(
                    value=str(item["quantite"]), width=60, dense=True,
                    text_align=ft.TextAlign.CENTER,
                    keyboard_type=ft.KeyboardType.NUMBER,
                    input_filter=ft.NumbersOnlyInputFilter(),
                    tooltip="Quantité",
                )
                qty_field.on_change = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, False)
                qty_field.on_blur = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, True)
                qty_field.on_submit = lambda e, i=id_art, f=qty_field, t=subtotal_text: set_cart_qty(i, f, t, True)

                btn_minus = ft.IconButton(icon=ft.Icons.REMOVE_CIRCLE_OUTLINE, tooltip="Diminuer",
                                          on_click=lambda e, i=id_art: update_cart_qty(i, -1))
                btn_plus = ft.IconButton(icon=ft.Icons.ADD_CIRCLE_OUTLINE, tooltip="Augmenter",
                                         on_click=lambda e, i=id_art: update_cart_qty(i, 1))
                btn_delete = ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                                           tooltip="Retirer du panier",
                                           visual_density=ft.VisualDensity.COMPACT,
                                           on_click=lambda e, i=id_art: remove_cart_line(i))

                cart_listview.controls.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Row([
                                ft.Text(item["Nom"], weight=ft.FontWeight.W_500, expand=True),
                                btn_delete,
                            ], vertical_alignment=ft.CrossAxisAlignment.START),
                            ft.Text(f"{fmt_eur(item['Prix'])} / unité", size=12, color=ft.Colors.GREY_700),
                            ft.Row([
                                ft.Row([btn_minus, qty_field, btn_plus], spacing=0),
                                subtotal_text,
                            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        ], spacing=2),
                        padding=ft.Padding.only(left=10, right=4, top=6, bottom=10),
                        border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_300)),
                    )
                )

        update_cart_summary()

    def update_cart_summary():
        """Total en bas du panier et nombre d'articles dans l'onglet « Panier »."""
        order = current_order()
        total_text.value = f"Total : {fmt_eur(order_total(order))}"
        n = order_count(order)
        cart_tab.label = f"🛍️ Panier ({n})" if n else "🛍️ Panier"

    # --- RENDU DU MENU LATÉRAL (liste des commandes) ---
    def order_handlers(order_id):
        """Crée les actions d'une ligne de commande (sélection, renommer, supprimer)."""
        async def on_select(e):
            await select_order(order_id)

        async def on_rename(e):
            await rename_order_dialog(order_id)

        async def on_delete(e):
            await delete_order_dialog(order_id)

        return on_select, on_rename, on_delete

    def render_orders():
        n_total = len(cat["all"])
        n_visible = len(visible_entries())
        controls = [
            ft.Container(
                padding=ft.Padding.only(left=16, right=16, top=16, bottom=8),
                content=ft.Row([
                    ft.Icon(ft.Icons.RECEIPT_LONG, color=ft.Colors.BLUE_900),
                    ft.Text("Prise de Commande", size=18, weight=ft.FontWeight.BOLD,
                            color=ft.Colors.BLUE_900),
                ]),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=12, vertical=4),
                content=ft.Row([
                    ft.Button(
                        content="Nouvelle commande",
                        icon=ft.Icons.EDIT_SQUARE,
                        on_click=create_order_dialog,
                        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
                        expand=True,
                    ),
                ]),
            ),
            ft.Container(
                padding=ft.Padding.symmetric(horizontal=8),
                content=ft.ListTile(
                    dense=True,
                    shape=ft.RoundedRectangleBorder(radius=10),
                    leading=ft.Icon(ft.Icons.TUNE, color=ft.Colors.BLUE_900),
                    title=ft.Text("Gérer les articles", weight=ft.FontWeight.W_500),
                    subtitle=ft.Text(f"{n_visible} affichés sur {n_total}", size=12),
                    on_click=open_admin,
                ),
            ),
            ft.Divider(height=1),
            ft.Container(
                padding=ft.Padding.only(left=16, top=12, bottom=4),
                content=ft.Text("Commandes", size=12, weight=ft.FontWeight.W_600,
                                color=ft.Colors.GREY_700),
            ),
        ]

        if not orders:
            controls.append(ft.Container(
                padding=ft.Padding.symmetric(horizontal=16, vertical=8),
                content=ft.Text(
                    "Aucune commande pour l'instant.\n"
                    "Appuyez sur « Nouvelle commande » pour commencer.",
                    size=13, italic=True, color=ft.Colors.GREY_600,
                ),
            ))

        # Les plus récentes en premier (le dict garde l'ordre de création)
        for order_id in reversed(list(orders)):
            order = orders[order_id]
            is_active = order_id == state["current"]
            created = datetime.fromisoformat(order["created"]).strftime("%d/%m")
            on_select, on_rename, on_delete = order_handlers(order_id)

            controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=8),
                    content=ft.ListTile(
                        dense=True,
                        shape=ft.RoundedRectangleBorder(radius=10),
                        title=ft.Text(
                            order["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            weight=ft.FontWeight.BOLD if is_active else ft.FontWeight.NORMAL,
                        ),
                        subtitle=ft.Text(
                            f"{created} · {order_count(order)} art. · {fmt_eur(order_total(order))}"
                            + (f" · 📷 {len(order['photos'])}" if order.get("photos") else ""),
                            size=12,
                        ),
                        trailing=ft.PopupMenuButton(
                            icon=ft.Icons.MORE_VERT,
                            tooltip="Options",
                            items=[
                                ft.PopupMenuItem(content="Renommer", icon=ft.Icons.EDIT_OUTLINED,
                                                 on_click=on_rename),
                                ft.PopupMenuItem(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE,
                                                 on_click=on_delete),
                            ],
                        ),
                        selected=is_active,
                        selected_color=ft.Colors.BLUE_900,
                        selected_tile_color=ft.Colors.BLUE_100,
                        on_click=on_select,
                    ),
                )
            )

        drawer.controls = controls

    def render_all():
        if state["current"] is None:
            # Pas de commande : écran d'aide à la place du catalogue / panier
            appbar_title.value = "Prise de Commande"
            body.content = empty_state
        else:
            appbar_title.value = current_order()["name"]
            body.content = tabs
            render_cart()
            render_photos()
        render_orders()

    # =====================================================================
    # --- ÉCRAN « GÉRER LES ARTICLES » : affichage, prix, articles ajoutés ---
    # =====================================================================

    admin_search = ft.TextField(
        label="Rechercher",
        prefix_icon=ft.Icons.SEARCH,
        expand=3,
    )
    admin_category = ft.Dropdown(
        label="Catégorie",
        options=[],
        value="Toutes",
        expand=2,
    )
    # Filtre Tous / Affichés / Masqués (les nombres sont mis à jour par refresh_admin_info)
    admin_visibility = ft.SegmentedButton(
        segments=[
            ft.Segment(value="tous", label="Tous"),
            ft.Segment(value="affiches", label="Affichés"),
            ft.Segment(value="masques", label="Masqués"),
        ],
        selected=["tous"],
        allow_empty_selection=False,
        allow_multiple_selection=False,
        show_selected_icon=False,
        expand=True,
    )
    admin_listview = ft.ListView(expand=True, spacing=0, padding=ft.Padding.only(bottom=24))

    # Références vers les contrôles affichés, pour les mettre à jour sans tout redessiner
    admin_rows = {}     # clé article → contrôles de la ligne
    admin_headers = {}  # catégorie → (case à cocher, compteur, clés des articles affichés)

    def admin_filtered():
        search_val = admin_search.value or ""
        cat_val = admin_category.value
        visibility = (admin_visibility.selected or ["tous"])[0]
        return [
            e for e in cat["all"]
            if matches_search(e["Nom_Article"], search_val)
            and (cat_val == "Toutes" or e["Categorie"] == cat_val)
            and (visibility == "tous" or e["Visible"] == (visibility == "affiches"))
        ]

    async def on_admin_filter(e=None):
        render_admin()
        refresh()
        await admin_listview.scroll_to(offset=0)  # résultats affichés depuis le début

    admin_search.on_change = on_admin_filter
    admin_category.on_select = on_admin_filter
    admin_visibility.on_change = on_admin_filter

    def refresh_admin_info():
        n_visible = len(visible_entries())
        n_total = len(cat["all"])
        labels = {"tous": f"Tous {n_total}", "affiches": f"Affichés {n_visible}",
                  "masques": f"Masqués {n_total - n_visible}"}
        for segment in admin_visibility.segments:
            segment.label = labels[segment.value]

    def refresh_admin_row(key):
        refs = admin_rows.get(key)
        entry = entry_by_key(key)
        if not refs or not entry:
            return
        refs["checkbox"].value = entry["Visible"]
        refs["name"].color = None if entry["Visible"] else ft.Colors.GREY_500
        modified = not entry["Perso"] and abs(entry["Prix_Unitaire"] - entry["Prix_Excel"]) >= 0.005
        if entry["Perso"]:
            refs["detail"].value = "Article ajouté"
        elif modified:
            refs["detail"].value = f"Prix modifié (Excel : {fmt_eur(entry['Prix_Excel'])})"
        else:
            refs["detail"].value = ""
        refs["detail"].visible = bool(refs["detail"].value)
        if "reset" in refs:
            refs["reset"].visible = modified

    def refresh_admin_header(categorie):
        if categorie not in admin_headers:
            return
        checkbox, counter, keys = admin_headers[categorie]
        entries = [entry_by_key(k) for k in keys]
        n_visible = sum(1 for e in entries if e and e["Visible"])
        # Case « mixte » (−) seulement quand une partie est cochée. Une case à 3 états à False
        # s'affiche « − » dans Flet : on ne garde le 3e état que lorsqu'il sert.
        mixed = 0 < n_visible < len(entries)
        checkbox.tristate = mixed
        checkbox.value = None if mixed else n_visible == len(entries)
        counter.value = f"{n_visible}/{len(entries)}"

    def set_visible(keys, visible):
        for key in keys:
            if visible:
                prefs["hidden"].discard(key)
            else:
                prefs["hidden"].add(key)
        persist_prefs()
        rebuild_catalogue()
        for key in keys:
            refresh_admin_row(key)
        for categorie in {entry_by_key(k)["Categorie"] for k in keys if entry_by_key(k)}:
            refresh_admin_header(categorie)
        refresh_admin_info()
        refresh()

    def toggle_category(categorie):
        # Tout est coché → on décoche tout ; sinon on coche tout (articles affichés par le filtre)
        keys = admin_headers[categorie][2]
        all_visible = all(entry_by_key(k)["Visible"] for k in keys)
        set_visible(keys, not all_visible)

    def commit_price(key, field, final):
        """Enregistre le prix saisi. final=True (sortie du champ / Entrée) : remet le champ au propre."""
        entry = entry_by_key(key)
        if not entry:
            return
        price = _to_price(field.value)
        if price is None or price < 0:
            if final:
                field.value = fmt_input(entry['Prix_Unitaire'])
                show_snack("Prix invalide : saisissez un nombre, ex. 1190 ou 79,50.")
                refresh()
            return
        price = round(price, 2)
        if entry["Perso"]:
            for c in prefs["custom"]:
                if c["key"] == key:
                    c["price"] = price
        elif abs(price - entry["Prix_Excel"]) < 0.005:
            prefs["prices"].pop(key, None)  # retour au prix de l'Excel
        else:
            prefs["prices"][key] = price
        if abs(price - entry["Prix_Unitaire"]) >= 0.005:
            persist_prefs()
            rebuild_catalogue()
            refresh_admin_row(key)
        if final:
            field.value = fmt_input(price)

    def reset_price(key, field):
        prefs["prices"].pop(key, None)
        persist_prefs()
        rebuild_catalogue()
        entry = entry_by_key(key)
        field.value = fmt_input(entry['Prix_Unitaire'])
        refresh_admin_row(key)
        show_snack(f"Prix Excel rétabli : {fmt_eur(entry['Prix_Unitaire'])}")
        refresh()

    def admin_row(entry):
        key = entry["Cle"]
        checkbox = ft.Checkbox(
            value=entry["Visible"],
            tooltip="Afficher dans le catalogue",
            on_change=lambda e, k=key: set_visible([k], bool(e.control.value)),
        )
        name = ft.Text(entry["Nom_Article"], weight=ft.FontWeight.W_500, size=14)
        detail = ft.Text("", size=11, color=ft.Colors.ORANGE_800, italic=True)
        price_field = ft.TextField(
            value=fmt_input(entry['Prix_Unitaire']),
            width=118,  # assez large pour « 1350,00 € »
            dense=True,
            text_align=ft.TextAlign.RIGHT,
            suffix="€",
            keyboard_type=ft.KeyboardType.NUMBER,
            tooltip="Prix unitaire",
        )
        price_field.on_change = lambda e, k=key, f=price_field: commit_price(k, f, final=False)
        price_field.on_blur = lambda e, k=key, f=price_field: commit_price(k, f, final=True)
        price_field.on_submit = lambda e, k=key, f=price_field: commit_price(k, f, final=True)

        refs = {"checkbox": checkbox, "name": name, "detail": detail}
        if entry["Perso"]:
            extra = ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE, icon_color=ft.Colors.RED_400,
                tooltip="Supprimer cet article",
                visual_density=ft.VisualDensity.COMPACT,
                on_click=lambda e, k=key: delete_article_dialog(k),
            )
        else:
            extra = ft.IconButton(
                icon=ft.Icons.RESTART_ALT,
                tooltip="Revenir au prix de l'Excel",
                visual_density=ft.VisualDensity.COMPACT,
                on_click=lambda e, k=key, f=price_field: reset_price(k, f),
            )
            refs["reset"] = extra
        admin_rows[key] = refs
        refresh_admin_row(key)

        return ft.Container(
            padding=ft.Padding.only(left=0, right=4, top=4, bottom=4),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_200)),
            content=ft.Row(
                [
                    checkbox,
                    ft.Column([name, detail], spacing=0, expand=True, tight=True),
                    price_field,
                    # largeur fixe : les champs de prix restent alignés, bouton visible ou non
                    ft.Container(content=extra, width=40),
                ],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def render_admin():
        admin_listview.controls.clear()
        admin_rows.clear()
        admin_headers.clear()

        categories = categories_of(cat["all"])
        admin_category.options = [ft.DropdownOption(key=c, text=c) for c in ["Toutes"] + sorted(categories)]
        if admin_category.value not in categories:
            admin_category.value = "Toutes"

        filtered = admin_filtered()
        if not filtered:
            admin_listview.controls.append(ft.Container(
                padding=16, content=ft.Text("Aucun article ne correspond.", italic=True)))

        for categorie in categories:
            group = [e for e in filtered if e["Categorie"] == categorie]
            if not group:
                continue
            header_checkbox = ft.Checkbox(
                tooltip="Tout cocher / tout décocher",
                on_change=lambda e, c=categorie: toggle_category(c),
            )
            counter = ft.Text("", size=12, color=ft.Colors.GREY_700)
            admin_headers[categorie] = (header_checkbox, counter, [e["Cle"] for e in group])
            admin_listview.controls.append(ft.Container(
                bgcolor=ft.Colors.BLUE_50,
                border_radius=5,
                margin=ft.Margin.only(top=10),
                padding=ft.Padding.only(left=0, right=12, top=2, bottom=2),
                content=ft.Row([
                    header_checkbox,
                    ft.Text(f"{get_category_icon(categorie)} {categorie}", size=16,
                            weight=ft.FontWeight.BOLD, expand=True),
                    counter,
                ]),
            ))
            refresh_admin_header(categorie)
            for entry in group:
                admin_listview.controls.append(admin_row(entry))
        refresh_admin_info()

    def add_article_dialog(e=None):
        categories = categories_of(cat["all"])
        new_cat_key = "__nouvelle__"
        initial_cat = admin_category.value if admin_category.value in categories else (
            categories[0] if categories else new_cat_key)

        name_field = ft.TextField(label="Nom de l'article", autofocus=True,
                                  capitalization=ft.TextCapitalization.SENTENCES)
        new_cat_field = ft.TextField(label="Nom de la nouvelle catégorie",
                                     capitalization=ft.TextCapitalization.SENTENCES,
                                     visible=initial_cat == new_cat_key)
        cat_field = ft.Dropdown(
            label="Catégorie",
            options=[ft.DropdownOption(key=c, text=c) for c in categories]
                    + [ft.DropdownOption(key=new_cat_key, text="➕ Nouvelle catégorie…")],
            value=initial_cat,
            width=400,
        )
        cat_field.on_select = lambda e: setattr(new_cat_field, "visible", cat_field.value == new_cat_key)
        price_field = ft.TextField(label="Prix unitaire", suffix="€", keyboard_type=ft.KeyboardType.NUMBER)
        error_text = ft.Text("", color=ft.Colors.RED, size=12, visible=False)

        def fail(message):
            error_text.value = message
            error_text.visible = True

        def validate(e=None):
            name = norm_text(name_field.value or "")
            category = norm_text(new_cat_field.value or "") if cat_field.value == new_cat_key else cat_field.value
            price = _to_price(price_field.value)
            if not name:
                return fail("Indiquez le nom de l'article.")
            if not category:
                return fail("Indiquez le nom de la nouvelle catégorie.")
            if price is None or price < 0:
                return fail("Prix invalide : saisissez un nombre, ex. 1190 ou 79,50.")
            page.pop_dialog()
            prefs["custom"].append({
                "key": KEY_PERSO + uuid.uuid4().hex[:8],
                "name": name,
                "category": category,
                "price": round(price, 2),
            })
            persist_prefs()
            rebuild_catalogue()
            render_admin()
            show_snack(f"➕ « {name} » ajouté dans « {category} »")
            refresh()

        name_field.on_submit = validate
        price_field.on_submit = validate
        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Ajouter un article"),
            content=ft.Column([name_field, cat_field, new_cat_field, price_field, error_text],
                              tight=True, spacing=12, width=400),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.Button(content="Ajouter", on_click=validate),
            ],
        ))

    def delete_article_dialog(key):
        entry = entry_by_key(key)
        if not entry:
            return

        def confirm(e):
            page.pop_dialog()
            if not any(c["key"] == key for c in prefs["custom"]):  # double appui
                return
            prefs["custom"] = [c for c in prefs["custom"] if c["key"] != key]
            prefs["hidden"].discard(key)
            persist_prefs()
            rebuild_catalogue()
            render_admin()
            show_snack(f"🗑️ « {entry['Nom_Article']} » supprimé du catalogue.")
            refresh()

        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Supprimer l'article ?"),
            content=ft.Text(f"« {entry['Nom_Article']} » sera retiré du catalogue.\n"
                            "Les commandes qui le contiennent déjà ne changent pas."),
            actions=[
                ft.TextButton(content="Annuler", on_click=lambda e: page.pop_dialog()),
                ft.Button(content="Supprimer", on_click=confirm,
                          style=ft.ButtonStyle(bgcolor=ft.Colors.RED, color=ft.Colors.WHITE)),
            ],
        ))

    admin_view = ft.View(
        route="/articles",
        padding=10,
        appbar=ft.AppBar(
            title=ft.Text("Gérer les articles", weight=ft.FontWeight.W_600),
            bgcolor=ft.Colors.BLUE_50,
            actions=[
                ft.TextButton(content="Ajouter", icon=ft.Icons.ADD, tooltip="Ajouter un article",
                              on_click=add_article_dialog),
            ],
        ),
        controls=[
            ft.SafeArea(expand=True, content=ft.Column(
                [
                    ft.Container(padding=ft.Padding.only(top=6),
                                 content=ft.Row([admin_search, admin_category])),
                    ft.Row([admin_visibility]),
                    admin_listview,
                ],
                expand=True,
            )),
        ],
    )

    # =====================================================================
    # --- PHOTOS DE LA COMMANDE (matériel à remplacer) ---
    # =====================================================================

    file_picker = ft.FilePicker()  # services : on garde une référence
    share = ft.Share()
    is_mobile = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
    camera_available = fc is not None and is_mobile
    camera_state = {"cam": None}

    photos_tab = ft.Tab(label="📷 Photos")  # libellé mis à jour avec le nombre de photos
    photos_grid = ft.GridView(
        expand=True, max_extent=200, child_aspect_ratio=0.8,
        spacing=10, run_spacing=10, padding=ft.Padding.only(top=4, bottom=12),
    )
    photos_empty = ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=24,
        content=ft.Column(
            [
                ft.Icon(ft.Icons.PHOTO_CAMERA_OUTLINED, size=56, color=ft.Colors.BLUE_200),
                ft.Text("Aucune photo pour cette commande", weight=ft.FontWeight.BOLD),
                ft.Text("Photographiez le matériel à remplacer : étiquettes, numéros de série, "
                        "branchements… puis donnez un nom à chaque photo.",
                        text_align=ft.TextAlign.CENTER, color=ft.Colors.GREY_700, size=13),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True, spacing=8,
        ),
    )

    def order_photos(order=None):
        return (order or current_order()).setdefault("photos", [])

    def add_photo_file(order_id, source_path=None, data=None, ext=".jpg"):
        """Range une photo (copie d'un fichier, ou octets de l'appareil photo) dans la commande."""
        folder = photos_dir(order_id)
        folder.mkdir(parents=True, exist_ok=True)
        photo_id = uuid.uuid4().hex[:8]
        filename = photo_id + (ext if ext.startswith(".") else "." + ext)
        if data is not None:
            (folder / filename).write_bytes(data)
        else:
            shutil.copyfile(source_path, folder / filename)
        photos = orders[order_id].setdefault("photos", [])
        entry = {"id": photo_id, "file": filename, "label": f"Photo {len(photos) + 1}",
                 "added": datetime.now().isoformat(timespec="minutes")}
        photos.append(entry)
        return entry

    def delete_photo(order_id, photo_id):
        photos = orders[order_id].get("photos", [])
        photo = next((p for p in photos if p["id"] == photo_id), None)
        if photo is None:
            return None
        photos.remove(photo)
        try:
            photo_path(order_id, photo).unlink()
        except OSError:
            pass
        return photo

    def render_photos():
        order_id = state["current"]
        photos = order_photos()
        photos_grid.controls.clear()
        for i, photo in enumerate(photos, 1):
            photos_grid.controls.append(ft.Container(
                bgcolor=ft.Colors.GREY_100,
                border_radius=10,
                padding=6,
                ink=True,
                tooltip="Renommer ou supprimer",
                on_click=lambda e, pid=photo["id"]: open_photo_dialog(pid),
                content=ft.Column(
                    [
                        ft.Image(
                            src=str(photo_path(order_id, photo)),
                            fit=ft.BoxFit.COVER,
                            height=150,
                            cache_width=400,  # vignette : évite de décoder l'image en pleine taille
                            border_radius=8,
                            error_content=ft.Icon(ft.Icons.BROKEN_IMAGE_OUTLINED, color=ft.Colors.GREY_500),
                        ),
                        ft.Text(f"{i}. {photo['label']}", size=12, weight=ft.FontWeight.W_500,
                                max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                    spacing=6,
                    horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                ),
            ))
        has_photos = bool(photos)
        photos_grid.visible = has_photos
        photos_empty.visible = not has_photos
        share_photos_btn.disabled = not has_photos
        zip_photos_btn.disabled = not has_photos
        photos_tab.label = f"📷 Photos ({len(photos)})" if has_photos else "📷 Photos"

    def ask_photo_label(order_id, photo, title, on_done=None, image_src=None, modal=True):
        """Boîte « nommer la photo » : aperçu, libellé, Supprimer / Enregistrer.
        modal=False : un appui à côté ferme la boîte (simple consultation)."""
        label_field = ft.TextField(
            value=photo["label"],
            label="Nom de la photo",
            hint_text="ex. Ancien serveur – étiquette",
            capitalization=ft.TextCapitalization.SENTENCES,
            autofocus=True,
        )

        def save(e=None):
            page.pop_dialog()
            label = norm_text(label_field.value or "")
            if label and label != photo["label"]:
                photo["label"] = label
                persist()
            render_all()
            if on_done:
                on_done()
            refresh()

        def remove(e):
            page.pop_dialog()
            if delete_photo(order_id, photo["id"]):
                persist()
                render_all()
                show_snack("🗑️ Photo supprimée.")
            if on_done:
                on_done()
            refresh()

        label_field.on_submit = save
        added = datetime.fromisoformat(photo["added"]).strftime("%d/%m/%Y à %H:%M")
        page.show_dialog(ft.AlertDialog(
            modal=modal,
            title=ft.Text(title),
            content=ft.Column(
                [
                    ft.Image(src=image_src or str(photo_path(order_id, photo)), fit=ft.BoxFit.CONTAIN,
                             height=260, cache_width=1080, border_radius=8),
                    label_field,
                    ft.Text(f"Prise le {added}", size=11, color=ft.Colors.GREY_600),
                ],
                tight=True, spacing=10, width=420,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            actions_alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            actions=[
                ft.TextButton(content="Supprimer", icon=ft.Icons.DELETE_OUTLINE, on_click=remove,
                              style=ft.ButtonStyle(color=ft.Colors.RED)),
                ft.Button(content="Enregistrer", on_click=save),
            ],
        ))

    def open_photo_dialog(photo_id):
        order_id = state["current"]
        photo = next((p for p in order_photos() if p["id"] == photo_id), None)
        if photo is None:
            return
        ask_photo_label(order_id, photo, "Photo", modal=False)
        refresh()

    async def import_photos(e=None):
        """Galerie du téléphone, ou fichiers sur PC (plusieurs à la fois)."""
        order_id = state["current"]
        if order_id is None:
            return
        try:
            files = await file_picker.pick_files(
                dialog_title="Choisir des photos",
                file_type=ft.FilePickerFileType.IMAGE,
                allow_multiple=True,
            )
        except Exception as err:  # sélecteur indisponible
            show_snack(f"Impossible d'ouvrir la galerie : {err}")
            refresh()
            return
        if not files:
            return  # annulé
        added, failed = 0, 0
        for f in files:
            if not f.path:
                failed += 1
                continue
            ext = os.path.splitext(f.name or f.path)[1].lower() or ".jpg"
            try:
                add_photo_file(order_id, source_path=f.path, ext=ext)
                added += 1
            except OSError:
                failed += 1
        persist()
        render_all()
        go_to_tab(2)
        message = f"📷 {added} photo(s) ajoutée(s) — touchez une photo pour la nommer."
        if failed:
            message += f" {failed} n'ont pas pu être copiée(s)."
        show_snack(message)
        refresh()

    async def share_photos(e=None):
        """Feuille de partage du téléphone (mail, WhatsApp, Drive…) : photos nommées + liste."""
        order_id, order = state["current"], current_order()
        if not order.get("photos"):
            return
        names = photo_export_names(order)
        # Copies portant le libellé comme nom de fichier (le destinataire voit « 01 - Ancien serveur.jpg »)
        export_dir = storage_dir() / "export" / order_id
        shutil.rmtree(export_dir, ignore_errors=True)
        export_dir.mkdir(parents=True, exist_ok=True)
        files = []
        for photo, name in zip(order["photos"], names):
            target = export_dir / name
            shutil.copyfile(photo_path(order_id, photo), target)
            files.append(ft.ShareFile.from_path(str(target), name=name))
        try:
            await share.share_files(
                files,
                subject=f"Photos – {order['name']}",
                text="\n".join(photos_summary(order, names)),
            )
        except Exception as err:
            show_snack(f"Partage impossible : {err}")
            refresh()

    async def save_photos_zip(e=None):
        """Un fichier .zip : photos nommées par leur libellé + photos.txt (liste et articles)."""
        order_id, order = state["current"], current_order()
        if not order.get("photos"):
            return
        data = build_photos_zip(order_id, order)
        file_name = f"{safe_filename(order['name'], 'commande')} - photos.zip"
        try:
            chosen = await file_picker.save_file(
                dialog_title="Enregistrer les photos",
                file_name=file_name,
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["zip"],
                src_bytes=data,
            )
        except Exception as err:
            show_snack(f"Enregistrement impossible : {err}")
            refresh()
            return
        if not chosen:
            return  # annulé
        if not is_mobile:
            # Sur PC, le sélecteur renvoie l'emplacement choisi : c'est l'app qui écrit le fichier
            target = Path(chosen)
            if target.suffix.lower() != ".zip":
                target = target.with_suffix(".zip")
            try:
                target.write_bytes(data)
            except OSError as err:
                show_snack(f"Enregistrement impossible : {err}")
                refresh()
                return
            chosen = str(target)
        show_snack(f"💾 Photos enregistrées : {Path(chosen).name}")
        refresh()

    # --- Appareil photo intégré (Android) ---
    camera_count = ft.Text("", color=ft.Colors.WHITE, size=13, width=90)

    def update_camera_count():
        n = len(order_photos()) if state["current"] else 0
        camera_count.value = f"{n} photo(s)" if n else ""

    def build_camera_view():
        cam = fc.Camera(expand=True)
        camera_state["cam"] = cam
        update_camera_count()
        return ft.View(
            route="/photo",
            bgcolor=ft.Colors.BLACK,
            padding=0,
            appbar=ft.AppBar(
                title=ft.Text(current_order()["name"], max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                bgcolor=ft.Colors.BLACK,
                color=ft.Colors.WHITE,
                actions=[ft.TextButton(content="Terminé", on_click=close_camera,
                                       style=ft.ButtonStyle(color=ft.Colors.WHITE))],
            ),
            controls=[ft.SafeArea(expand=True, content=ft.Column(
                [
                    cam,
                    ft.Container(
                        padding=ft.Padding.symmetric(horizontal=20, vertical=14),
                        content=ft.Row(
                            [
                                camera_count,
                                ft.IconButton(
                                    icon=ft.Icons.CAMERA, icon_size=40, icon_color=ft.Colors.WHITE,
                                    bgcolor=ft.Colors.BLUE, width=76, height=76,
                                    tooltip="Prendre la photo", on_click=take_photo,
                                ),
                                ft.Container(width=90),
                            ],
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        ),
                    ),
                ],
                expand=True, spacing=0,
            ))],
        )

    async def open_camera(e=None):
        if not camera_available or state["current"] is None:
            await import_photos()
            return
        state["back_to_photos"] = True
        await page.push_route("/photo")  # la caméra démarre dans route_change, une fois l'écran affiché

    async def start_camera():
        cam = camera_state["cam"]
        await asyncio.sleep(0.4)  # le temps que l'aperçu soit créé à l'écran
        try:
            cameras = await cam.get_available_cameras()
            if not cameras:
                raise RuntimeError("aucun appareil photo trouvé")
            back = next((c for c in cameras if c.lens_direction == fc.CameraLensDirection.BACK), cameras[0])
            await cam.initialize(back, fc.ResolutionPreset.HIGH, enable_audio=False)
        except Exception as err:
            camera_state["cam"] = None
            await page.push_route("/")
            show_snack(f"Appareil photo indisponible ({err}). Utilisez « Importer ».")
            refresh()

    async def take_photo(e=None):
        cam, order_id = camera_state["cam"], state["current"]
        if cam is None or order_id is None:
            return
        try:
            data = await cam.take_picture()
        except Exception as err:
            show_snack(f"Photo impossible : {err}")
            refresh()
            return
        photo = add_photo_file(order_id, data=data, ext=".jpg")
        persist()
        update_camera_count()
        # On nomme la photo tout de suite, puis on reste dans l'appareil photo pour la suivante
        ask_photo_label(order_id, photo, "Nommer la photo", on_done=update_camera_count)
        refresh()

    async def close_camera(e=None):
        await page.push_route("/")

    async def open_admin(e=None):
        await close_drawer()
        await page.push_route("/articles")

    async def route_change(e=None):
        if page.route == "/articles":
            if len(page.views) == 1:
                render_admin()
                page.views.append(admin_view)
        elif page.route == "/photo":
            if len(page.views) == 1 and camera_available and state["current"] is not None:
                page.views.append(build_camera_view())
                refresh()
                await start_camera()
                return
        else:
            # Retour à l'écran principal : le catalogue reflète les changements
            while len(page.views) > 1:
                page.views.pop()
            camera_state["cam"] = None
            render_catalogue()
            render_all()
            if state.pop("back_to_photos", False) and state["current"] is not None:
                go_to_tab(2)  # retour de l'appareil photo : on montre les photos
        refresh()

    async def view_pop(e):
        # Flèche ← de la barre du haut, ou bouton « retour » d'Android
        await page.push_route("/")

    page.on_route_change = route_change
    page.on_view_pop = view_pop

    # --- CONSTRUCTION DE L'INTERFACE ---

    content_catalogue = ft.Column(
        [
            # marge en haut : l'étiquette « Catégorie » n'est plus coupée sous les onglets
            ft.Container(padding=ft.Padding.only(top=6),
                         content=ft.Row([search_input, category_dropdown])),
            catalogue_listview,
        ],
        expand=True,
    )

    content_panier = ft.Column(
        [
            cart_listview,
            ft.Divider(),
            total_text,
            ft.Row([
                ft.Button(
                    content="Copier pour la Compta",
                    icon=ft.Icons.COPY,
                    on_click=copy_email_text,
                    style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
                    expand=True,
                ),
            ]),
            ft.Row([
                ft.OutlinedButton(
                    content="Vider le panier",
                    icon=ft.Icons.DELETE,
                    on_click=clear_cart,
                    style=ft.ButtonStyle(color=ft.Colors.RED),
                    expand=True,
                ),
            ]),
        ],
        expand=True,
    )

    take_photo_btn = ft.Button(
        content="Prendre une photo", icon=ft.Icons.PHOTO_CAMERA, on_click=open_camera,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
        expand=True, visible=camera_available,
    )
    import_photos_btn = ft.OutlinedButton(
        content="Importer" if camera_available else "Importer des photos",
        icon=ft.Icons.PHOTO_LIBRARY_OUTLINED, on_click=import_photos, expand=True,
    )
    share_photos_btn = ft.Button(
        content="Partager les photos", icon=ft.Icons.SHARE, on_click=share_photos,
        style=ft.ButtonStyle(bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE),
        expand=True, visible=is_mobile,
    )
    zip_photos_btn = ft.OutlinedButton(
        content="Enregistrer en ZIP", icon=ft.Icons.FOLDER_ZIP_OUTLINED, on_click=save_photos_zip,
        expand=True,
    )
    content_photos = ft.Column(
        [
            ft.Container(padding=ft.Padding.only(top=8),
                         content=ft.Row([take_photo_btn, import_photos_btn])),
            photos_empty,
            photos_grid,
            ft.Divider(height=1),
            ft.Row([share_photos_btn]),
            ft.Row([zip_photos_btn]),
        ],
        expand=True,
    )

    # Flet 1.0 : Tabs = état partagé, TabBar = en-têtes, TabBarView = contenus
    cart_tab = ft.Tab(label="🛍️ Panier")  # libellé mis à jour avec le nombre d'articles
    tabs = ft.Tabs(
        length=3,
        selected_index=0,
        animation_duration=ft.Duration(milliseconds=300),
        expand=True,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(tabs=[
                    ft.Tab(label="📦 Catalogue"),
                    cart_tab,
                    photos_tab,
                ]),
                ft.TabBarView(
                    expand=True,
                    controls=[content_catalogue, content_panier, content_photos],
                ),
            ],
        ),
    )

    # Barre du haut : ☰ ouvre le menu latéral, titre = commande active, ✎ = nouvelle commande
    page.appbar = ft.AppBar(
        leading=ft.IconButton(icon=ft.Icons.MENU, tooltip="Commandes", on_click=open_drawer),
        title=appbar_title,
        bgcolor=ft.Colors.BLUE_50,
        actions=[
            ft.IconButton(icon=ft.Icons.EDIT_SQUARE, tooltip="Nouvelle commande",
                          on_click=create_order_dialog),
        ],
    )
    page.drawer = drawer

    # Écran d'aide affiché tant qu'aucune commande n'existe
    empty_state = ft.Container(
        expand=True,
        alignment=ft.Alignment.CENTER,
        padding=24,
        content=ft.Column(
            [
                ft.Icon(ft.Icons.RECEIPT_LONG, size=72, color=ft.Colors.BLUE_200),
                ft.Text("Aucune commande", size=22, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "Créez une commande et donnez-lui un nom (client, cabinet, salle…) "
                    "pour commencer à y ajouter des articles du catalogue.",
                    text_align=ft.TextAlign.CENTER,
                    color=ft.Colors.GREY_700,
                ),
                ft.Container(height=8),
                ft.Button(
                    content="Créer une commande",
                    icon=ft.Icons.ADD,
                    on_click=create_order_dialog,
                    style=ft.ButtonStyle(
                        bgcolor=ft.Colors.BLUE, color=ft.Colors.WHITE,
                        padding=ft.Padding.symmetric(horizontal=24, vertical=16),
                    ),
                ),
                ft.Text(
                    "Vos commandes seront ensuite accessibles avec le menu ☰ en haut à gauche.",
                    size=12, italic=True, text_align=ft.TextAlign.CENTER,
                    color=ft.Colors.GREY_600,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
            tight=True,
        ),
    )

    # Zone principale : affiche soit les onglets, soit l'écran d'aide (voir render_all)
    body = ft.Container(expand=True, content=tabs)

    # SafeArea : évite que l'interface passe sous les bords arrondis / encoches du téléphone
    page.add(ft.SafeArea(expand=True, content=body))
    render_catalogue()
    render_all()

    # Sauvegardes de démarrage : seulement si quelque chose a été converti ou créé
    if migrated:
        persist()
    if not prefs_path().exists():
        persist_prefs()  # garde les réglages par défaut (articles masqués par défaut)
    refresh()  # page.add() a déjà rafraîchi l'écran : on envoie le catalogue et le menu remplis ensuite

    if startup_warnings:
        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("⚠️ Attention"),
            content=ft.Text("\n\n".join(startup_warnings)),
            actions=[ft.Button(content="OK", on_click=lambda e: page.pop_dialog())],
        ))


# Démarrage de l'application
ft.run(main)
