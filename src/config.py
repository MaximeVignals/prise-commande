# Constantes de l'application (noms de fichiers, format du catalogue, préfixes de clés).

CATALOGUE_STEM = "catalogue_importe"                # catalogue importé par l'utilisateur (+ .xlsx ou .csv)
CATALOGUE_EXTENSIONS = (".xlsx", ".csv")
SAMPLE_CATALOGUE_FILENAME = "catalogue_modele.xlsx"  # catalogue fictif fourni avec le code (même format)
ORDERS_FILENAME = "commandes.json"
TEMPLATES_FILENAME = "modeles.json"
PREFS_FILENAME = "catalogue_perso.json"  # articles masqués, prix modifiés, articles ajoutés
BACKUPS_DIRNAME = "sauvegardes"  # copies de secours créées avant une restauration (voir backup.py)
RECOVERY_BACKUP_PATTERN = "avant-restauration-*.zip"

# Format du catalogue (voir FORMAT_CATALOGUE.md) : 1re feuille (ou CSV), ligne 1 = en-têtes
# « Catégorie | Article | Prix | Masqué ». Les 3 premières sont obligatoires, « Masqué » est facultative.
CATALOGUE_COLUMNS = {"categorie": "Catégorie", "article": "Article", "prix": "Prix", "masque": "Masqué"}
REQUIRED_COLUMNS = ("categorie", "article", "prix")
YES_VALUES = {"oui", "o", "x", "1", "yes", "y", "vrai", "true"}

# Préfixes des clés d'articles (identifiant stable, indépendant de la position dans l'Excel)
KEY_EXCEL = "XL:"
KEY_CATALOGUE = "CAT:"
KEY_PERSO = "PERSO:"
DEFAULT_CATALOGUE = ""
DEFAULT_CATALOGUE_LABEL = "Catalogue principal (sans préfixe)"
ALL_CATALOGUES = "__all_catalogues__"
