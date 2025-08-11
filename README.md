2. Ajout d’une image à la banque d’images

Toutes les images utilisées par Sikuli sont stockées dans un dossier dédié au projet, appelé sikuli-img.
Ce dossier sert de banque d’images accessible à l’ensemble des scripts Robot Framework qui utilisent Sikuli.

Pour ajouter une nouvelle image (par exemple un bouton sur lequel cliquer) :
	1.	Préparer l’interface :
Lancer l’application ou l’environnement dans l’état où le bouton est visible.
	2.	Prendre la capture avec Sikuli IDE :
	•	Ouvrir SikuliX IDE ou un utilitaire de capture d’écran.
	•	Sélectionner uniquement la zone correspondant au bouton (éviter les zones inutiles pour réduire les faux positifs).
	•	Enregistrer l’image en format .png dans le dossier sikuli-img du projet.
Exemple : sikuli-img/btn_valider.png
	3.	Nommer l’image clairement :
Utiliser un nom qui reflète son usage (btn_valider, icn_parametres, etc.) pour faciliter la maintenance.

⸻

3. Utilisation dans un script Robot Framework

Une fois l’image ajoutée, elle peut être utilisée dans un script Robot Framework grâce aux keywords fournis par SikuliLibrary.
