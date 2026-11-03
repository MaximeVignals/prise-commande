# Format du catalogue

L'application importe un fichier **`.xlsx`** (1re feuille) ou **`.csv`**. Au premier lancement, elle demande ce fichier. Pour le remplacer ensuite, ouvrez ☰ › **Importer un catalogue**.

Modèles prêts à remplir : [`modele/catalogue_modele.xlsx`](modele/catalogue_modele.xlsx) et [`modele/catalogue_modele.csv`](modele/catalogue_modele.csv).

## Règles

La **ligne 1** contient les en-têtes, écrits exactement comme ci-dessous (majuscules et accents facultatifs). L'ordre des colonnes n'a pas d'importance, et les autres colonnes sont ignorées.

| Colonne | Obligatoire | Contenu |
|---|---|---|
| `Catégorie` | oui | Nom de la catégorie, affiché tel quel. Les catégories apparaissent dans l'ordre du fichier. |
| `Article` | oui | Nom de l'article. Il sert d'identifiant : gardez le même nom d'un import à l'autre pour conserver paniers et prix modifiés. |
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
```

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
