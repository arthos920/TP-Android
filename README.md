#!/bin/bash

# Configuration
fichier="chemin/vers/ton_fichier.robot"  # <-- adapte ce chemin
tmp_fichier="${fichier}.tmp"

echo "Entrez le nombre de pions :"
read nb
echo "Latitude du centre :"
read lat
echo "Longitude du centre :"
read lon

echo "Génération de la ligne Robot Framework..."
ligne=$(python3 gen_ligne_robot.py "$nb" "$lat" "$lon")

# Vérifie que la ligne a été générée
if [ -z "$ligne" ]; then
    echo "Erreur : la ligne générée est vide."
    exit 1
fi

# Lecture ligne par ligne et écriture dans un fichier temporaire
echo "Traitement de $fichier..."
while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ "$line" == *"création mission custom"* ]]; then
        echo -e "$ligne" >> "$tmp_fichier"
    else
        echo "$line" >> "$tmp_fichier"
    fi
done < "$fichier"

# Sauvegarde du fichier original
cp "$fichier" "${fichier}.bak"

# Remplacement du fichier par la version modifiée
mv "$tmp_fichier" "$fichier"

echo "Remplacement terminé. Ligne insérée à la place de : 'création mission custom'"
