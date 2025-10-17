git config --global user.name "TonNomGitLab"
git config --global user.email "ton.email@domaine.com"





# 1️⃣ Récupérer la dernière version du dépôt et des branches
git fetch origin

# 2️⃣ Se baser sur la branche cible (solution-test)
git checkout solution-test
git pull origin solution-test

# 3️⃣ Créer ta nouvelle branche depuis solution-test
git checkout -b feature/ma-fonction

# 4️⃣ Ajouter tes fichiers modifiés
git add .

# 5️⃣ Committer tes changements
git commit -m "Ajout de la fonctionnalité ma-fonction"

# 6️⃣ Pousser ta branche sur GitLab
git push origin feature/ma-fonction