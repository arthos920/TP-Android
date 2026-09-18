Salut Benoit,

Oui je vois mieux ce que tu veux faire.

Je pense que je repartirais simplement d’un clone propre du repo GitLab correspondant à VM2, puis je créerais une branche dédiée pour intégrer les modifs de VM1.

Pour l’export VM1, je l’extraierais à part puis je recopierais les fichiers dans les bons répertoires du repo, en gardant exactement la même arborescence. Avant de commit, je vérifierais bien avec git status et git diff que les fichiers apparaissent aux bons endroits et qu’on ne recrée pas un sous-dossier en plus comme sur ton premier essai.

Ensuite :

commit + push de la branche sur GitLab 
sur VM2, récupération de cette branche
test pour vérifier que les customisations de VM1 sont bien présentes et que tout fonctionne.

Si c’est bon, on pourra ensuite merger et avoir une base Git commune pour VM1 et VM2.

Pour le repo qui apparaît directement dans ton home, je pense qu’il vaut mieux éviter de s’en servir si le repo utilisé pour le déploiement est bien celui sous /home/protocolEngine/data/codebase/user/public, histoire de ne pas multiplier les clones.

On peut regarder ensemble l’arborescence de l’export VM1 avant de refaire la manip, ça permettra de vérifier exactement où recopier les fichiers.

Cordialement,
