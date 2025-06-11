Dans le cadre de mon projet de fin d’études en tant qu’étudiant ingénieur, j’ai développé un script Bash destiné à automatiser la gestion des tests avec Robot Framework. Robot Framework est un framework de test d’acceptation populaire, principalement utilisé pour tester des applications d’interface utilisateur ou des APIs, souvent dans des environnements de développement agiles.

L’objectif principal du script est de simplifier l’exécution des tests et de les rendre plus flexibles et interactifs. Ce script permet à un utilisateur de sélectionner des tests spécifiques ou d’exécuter tous les tests d’un projet en un seul processus automatisé, en fonction des besoins.

Problématique

Lors de l’utilisation de Robot Framework dans des projets avec une grande quantité de fichiers de tests répartis dans plusieurs sous-dossiers, la gestion et l’exécution manuelle des tests peuvent rapidement devenir laborieuses. L’idée de ce projet était de créer un utilitaire qui permettrait de :
	•	Exécuter un ou plusieurs tests par sous-dossier.
	•	Changer de fichier de tests facilement.
	•	Sélectionner des tests spécifiques via un menu interactif.
	•	Modifier dynamiquement les fichiers .robot en fonction des besoins de génération de tests.

Ce script Bash s’inscrit dans une démarche d’automatisation de la gestion des tests pour améliorer l’efficacité des processus de tests dans un projet logiciel.

⸻

2. Objectifs et Fonctionnalités du Script

Objectif Principal

Le script développé permet de gérer facilement l’exécution des tests dans un environnement de projet contenant de nombreux fichiers de test, répartis dans plusieurs sous-dossiers.

Les fonctionnalités principales du script incluent :
	1.	Exécution des tests dans tout le projet ou dans des sous-dossiers spécifiques.
	2.	Sélection de tests individuels ou multiples pour une exécution ciblée.
	3.	Modification des fichiers de test en fonction de critères spécifiques (par exemple, ajouter une ligne de code à un test).
	4.	Affichage interactif des tests et gestion du projet via un menu.
	5.	Capacité de changer de dossier de projet et de recharger la configuration des tests.

Fonctionnalités Détaillées
	1.	Affichage des Sous-dossiers Disponibles :
L’option 1 permet de choisir et d’exécuter des tests dans un ou plusieurs sous-dossiers spécifiques, tels que authentication/, order/, etc. Cette option utilise la commande find pour lister les sous-dossiers du dossier tests/ et permet à l’utilisateur de sélectionner ceux qu’il souhaite exécuter.
	2.	Exécution de Tests Sélectionnés ou Multiples :
L’option 2 permet de choisir un fichier de test précis à exécuter, et l’option 3 permet de sélectionner plusieurs fichiers à la fois pour les exécuter ensemble.
	3.	Modification Dynamique des Fichiers de Test :
L’option 7 modifie chaque fichier .robot qui contient une ligne spécifique (“création mission custom”) en y insérant une nouvelle ligne générée dynamiquement via un script Python (gen_ligne_robot.py). Cette fonctionnalité permet d’adapter les tests sans avoir à les éditer manuellement.
	4.	Changement Dynamique de Projet :
L’option 4 permet à l’utilisateur de changer le dossier du projet à tout moment, en demandant le chemin d’un autre dossier my_project. Le script recharge alors les fichiers de test du nouveau projet.
	5.	Affichage de Tous les Tests Disponibles :
L’option 6 permet à l’utilisateur d’afficher tous les fichiers .robot disponibles dans le projet.

⸻

3. Développement et Structure du Script

Structure du Dossier

Le script suppose la structure suivante dans le projet :

my_project/
├── tests/
│   ├── authentication/
│   ├── master-data/
│   ├── order/
├── resources/


	•	tests/ contient les sous-dossiers avec les fichiers .robot de tests.
	•	resources/ contient les fichiers de ressources partagés entre les tests.

Fonctionnement Interactif

Le script présente un menu interactif permettant à l’utilisateur de sélectionner des actions :
	•	Option 1 : Exécuter tous les tests dans tests/.
	•	Option 2 : Exécuter un test spécifique parmi les fichiers disponibles.
	•	Option 3 : Exécuter plusieurs tests sélectionnés par l’utilisateur.
	•	Option 4 : Changer de projet en fournissant un nouveau chemin vers my_project.
	•	Option 5 : Quitter le script.
	•	Option 6 : Afficher tous les fichiers de tests disponibles.
	•	Option 7 : Modifier les fichiers .robot contenant “création mission custom” en insérant une ligne générée dynamiquement.

Sélection de Tests

Les tests sont stockés dans un tableau associatif test_files qui contient les chemins des fichiers .robot détectés dans le dossier tests/. Le script parcourt ces fichiers et permet à l’utilisateur de les sélectionner via le menu.

Exécution des Tests

Une fois que l’utilisateur a sélectionné les tests, les fichiers sont exécutés en utilisant la commande Robot Framework :

robot --pythonpath . "$file"


4. Résultats et Performances

Le script a permis d’atteindre les objectifs suivants :
	•	Facilité d’exécution : Les utilisateurs peuvent facilement sélectionner un ou plusieurs tests à exécuter grâce à l’interface interactive.
	•	Souplesse : Le script permet de choisir spécifiquement les tests ou les sous-dossiers à exécuter.
	•	Gain de temps : L’automatisation du processus d’exécution et de modification des tests permet de gagner du temps, notamment pour des projets avec plusieurs centaines de tests.

5. Limitations et Améliorations Possibles

Limitations
	•	Manipulation des tests par tags : Actuellement, le script ne prend pas en charge l’exécution des tests par tags comme dans les versions précédentes. Cependant, il pourrait être étendu pour réintégrer cette fonctionnalité.
	•	Interface graphique : Le script utilise un menu interactif en ligne de commande. Une interface graphique pourrait rendre l’utilisation plus conviviale pour les utilisateurs moins expérimentés.

Améliorations possibles
	•	Tests parallèles : Le script pourrait être modifié pour exécuter plusieurs tests en parallèle afin de réduire le temps d’exécution global, en particulier dans les grands projets.
	•	Gestion des résultats : Ajouter une fonctionnalité pour sauvegarder les résultats d’exécution dans des fichiers log ou dans une base de données pour un suivi et une analyse ultérieure.

⸻

6. Conclusion

Le script développé dans ce projet de fin d’études permet de simplifier et automatiser la gestion des tests avec Robot Framework. Il offre une solution flexible et rapide pour exécuter des tests sur de grands projets, avec la possibilité de filtrer les tests par sous-dossier ou par fichier, de modifier les fichiers de test, et de gérer facilement les chemins de projet.

Grâce à ce script, l’automatisation de l’exécution des tests devient plus accessible, ce qui est essentiel dans un environnement de développement moderne où les tests fréquents sont nécessaires pour garantir la qualité du code.
