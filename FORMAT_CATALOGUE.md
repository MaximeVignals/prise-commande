# Format du catalogue

L'application importe un fichier **`.xlsx`** (1re feuille) ou **`.csv`**. Au premier lancement, elle demande ce fichier. Pour le remplacer ensuite, ouvrez ☰ › **Importer un catalogue**.

Modèles prêts à remplir : [`modele/catalogue_modele.xlsx`](modele/catalogue_modele.xlsx) et [`modele/catalogue_modele.csv`](modele/catalogue_modele.csv).

## Règles

La **ligne 1** contient les en-têtes, écrits exactement comme ci-dessous (majuscules et accents facultatifs). L'ordre des colonnes n'a pas d'importance, et les autres colonnes sont ignorées.

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `Catégorie` | oui | Nom de la catégorie, ou `Catalogue:Catégorie` pour la placer dans un catalogue nommé. Les catégories apparaissent dans l'ordre du fichier. |
| `Article` | oui | Nom de l'article. Avec le catalogue, il sert d'identifiant : gardez ces deux noms d'un import à l'autre pour conserver le lien avec les paniers et prix modifiés. |
| `Prix` | oui | Prix unitaire en euros : `149`, `149,90`, `1 290,00 €` ou `1290.5`. |
| `Masqué` | non | `oui` pour que l'article soit masqué au départ. Il reste réactivable dans ☰ › Gérer les articles. Vide = affiché. |

- Une ligne = un article. Pas de lignes de titre, de sous-totaux, de lignes fusionnées ou de mise en forme à interpréter : le gras et les couleurs sont ignorés.
- Les lignes sans nom, sans catégorie ou sans prix lisible sont ignorées. L'application les liste après l'import.
- CSV : séparateur `;` (recommandé, s'ouvre bien dans Excel en français), `,` ou tabulation. Encodage UTF-8.

Exemple :

```csv
Catégorie;Article;Prix;Masqué
Écrans;Écran 24" Full HD;149,00;
Écrans;Écran 22" (ancien modèle);99,00;oui
Pc portable;Portable 14" i5 16 Go;899,00;
Prestations;Installation sur site (1 h);75,00;
Occasion:Écrans;Écran 24" Full HD;89,00;
Occasion:Pc portable;Portable 14" i5 16 Go;499,00;
```

## Plusieurs catalogues dans un fichier

Préfixez la catégorie par le nom du catalogue et un deux-points, sans crochets :
`Tarif matériel:Caméra` crée le catalogue **Tarif matériel** et y range l'article dans **Caméra**.
Les espaces autour du séparateur sont ignorés. Le premier deux-points sépare le catalogue
de la catégorie ; les suivants font partie du nom de la catégorie. Les noms ne doivent pas être vides.

Les catégories sans préfixe restent dans le **Catalogue principal (sans préfixe)**.
Les catalogues apparaissent dans l'ordre du fichier. Lorsqu'il y en a plusieurs, le sélecteur
**Catalogue** permet de passer de l'un à l'autre dans le catalogue et dans **Gérer les articles**.
La recherche, les catégories et la gestion des articles concernent le catalogue sélectionné.
Un article ajouté manuellement appartient au catalogue sélectionné dans **Gérer les articles**.

Ouvrez **☰ › Gérer les catalogues** pour afficher ou masquer chaque catalogue avec son
interrupteur. Un catalogue masqué disparaît du sélecteur de navigation. Il reste disponible
dans **Gérer les catalogues** et **Gérer les articles**. Ces choix sont enregistrés sur l'appareil
et conservés lors d'un nouvel import qui reprend les mêmes noms de catalogue.
Masquer un catalogue conserve les articles, leurs prix, leurs réglages individuels de visibilité
et les lignes déjà présentes dans les commandes. Si tous les catalogues sont masqués,
le bouton **Gérer les catalogues** permet d'en réactiver un depuis l'onglet Catalogue.

Dans **Gérer les catalogues**, le menu **⋮** de chaque ligne propose aussi :

- **Catalogue principal → Vider le catalogue principal** : retire tous ses articles importés
  et ajoutés manuellement. Le catalogue principal reste disponible dans la gestion, même vide.
- **Catalogue supplémentaire → Renommer** : change son nom localement, en conservant ses
  articles, leurs prix modifiés, leur visibilité et les liens avec les commandes.
- **Catalogue supplémentaire → Supprimer** : retire le catalogue et tous ses articles importés
  et ajoutés manuellement. Les commandes qui contiennent ces articles restent inchangées.

Vider et supprimer demandent une confirmation. Le nom d'un catalogue supplémentaire doit être
non vide, distinct des autres noms (sans distinction de casse ni d'accents) et sans deux-points.
Ces modifications sont enregistrées sur l'appareil ; le fichier Excel/CSV d'origine est conservé.
Un nouvel import remplace les modifications locales : il reprend les noms et les articles du
fichier importé. Les articles ajoutés manuellement qui ont été supprimés ne sont pas recréés.

Une même commande peut contenir des articles de plusieurs catalogues. Deux articles portant
le même nom dans des catalogues différents gardent leurs propres prix, réglages et lignes de panier.
Les anciens fichiers sans préfixe restent compatibles. Un nouvel import remplace l'ensemble
des catalogues importés : incluez tous les catalogues à conserver dans le même fichier.

## Convertir une liste de prix avec une IA (Gemini, ChatGPT, Claude…)

Envoyez votre fichier à l'assistant avec le message ci-dessous, puis enregistrez sa réponse dans un fichier `.csv` et ouvrez-le pour vérifier avant de l'importer. Complétez la partie « Particularités de mon fichier » avec ce qui s'applique au vôtre.

> Vérifiez que l'outil d'IA est autorisé pour vos données (prix, catalogue) avant de lui envoyer le fichier.

```text
Convertis le fichier joint en un catalogue CSV pour une application de prise de commande.

Format de sortie, à respecter strictement :
- Séparateur point-virgule (;), encodage UTF-8.
- Ligne 1, exactement : Catégorie;Article;Prix;Masqué
- Puis une ligne par article vendable, rien d'autre (pas de titres, de totaux ni de lignes vides).
- Catégorie : la catégorie de l'article, écrite proprement (ex. « Écrans », pas « ECRANS (EXEMPLE) »).
  Pour plusieurs catalogues, utilise « Catalogue:Catégorie » (ex. « Occasion:Écrans »).
- Article : le nom de l'article sur une seule ligne, sans retour à la ligne.
- Prix : prix unitaire en euros, nombre avec une virgule décimale, sans symbole (ex. 1290,00).
- Masqué : « oui » si l'article doit être masqué par défaut, sinon vide.
- Si un nom contient un point-virgule ou des guillemets, entoure-le de guillemets doubles
  et double les guillemets internes (ex. "Écran 24"" Full HD").

Particularités de mon fichier (à adapter) :
- Les lignes en gras sans prix sont des titres de catégorie : les articles en dessous appartiennent à cette catégorie.
- La colonne « Tarif neuf » est le prix à utiliser ; ignore les autres colonnes de prix.
- Les lignes sans prix sous un article (détails d'un pack, options, remarques) ne sont pas des articles : ignore-les.
- Ignore entièrement les sections : <noms des sections à retirer>.
- Masque par défaut les articles dont le nom contient : <mots>.
- Renomme les catégories : <ancien nom> → <nouveau nom>.

Donne uniquement le contenu CSV, dans un bloc de code, sans commentaire. Ensuite, en dehors du bloc,
liste les lignes du fichier d'origine que tu n'as pas su classer.
```
