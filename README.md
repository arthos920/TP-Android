#!/bin/bash

# === Initialisation ===
declare -a test_files

# === Fonction pour charger tous les fichiers .robot ===
load_all_tests() {
    test_files=()
    while IFS= read -r -d $'\0' file; do
        test_files+=("$file")
    done < <(find "$project_path/tests" -type f -name "*.robot" -print0)
}

# === Fonction pour exécuter un ou plusieurs fichiers ===
run_by_files() {
    local cmd="robot --pythonpath ."
    for file in "$@"; do
        cmd+=" \"$file\""
    done
    echo "Commande : $cmd"
    eval "$cmd"
}

# === Affichage de tous les fichiers ===
display_all_tests() {
    echo ""
    echo "Liste des fichiers de test disponibles :"
    for file in "${test_files[@]}"; do
        echo "- $file"
    done
}

# === Demander le dossier my_project ===
echo "Veuillez entrer le chemin absolu du dossier 'my_project' :"
read project_path

if [[ ! -d "$project_path/tests" ]]; then
    echo "Erreur : le dossier 'tests' est introuvable dans $project_path"
    exit 1
fi

cd "$project_path" || exit 1
load_all_tests

# === Menu principal ===
while true; do
    echo ""
    echo "===== MENU ====="
    echo "1. Exécuter tous les fichiers de test"
    echo "2. Sélectionner un fichier à exécuter"
    echo "3. Sélectionner plusieurs fichiers"
    echo "4. Changer de dossier my_project"
    echo "5. Quitter"
    echo "6. Afficher tous les tests disponibles"
    echo "7. Modifier chaque fichier avec ligne 'création mission custom'"
    echo "================"
    read -p "Votre choix : " choice

    case $choice in
        1)
            echo "Exécution de tous les fichiers..."
            run_by_files "${test_files[@]}"
            ;;
        2)
            echo "Fichiers disponibles :"
            select file in "${test_files[@]}"; do
                if [[ -n "$file" ]]; then
                    run_by_files "$file"
                    break
                else
                    echo "Sélection invalide."
                fi
            done
            ;;
        3)
            selected_files=()
            echo "Fichiers disponibles :"
            select file in "${test_files[@]}"; do
                if [[ -n "$file" ]]; then
                    selected_files+=("$file")
                    echo "$file ajouté."
                    read -p "Ajouter un autre fichier ? (y/n) : " rep
                    if [[ "$rep" != "y" ]]; then
                        break
                    fi
                else
                    echo "Sélection invalide."
                fi
            done
            echo "Exécution des fichiers sélectionnés..."
            run_by_files "${selected_files[@]}"
            ;;
        4)
            read -p "Entrez le nouveau chemin de 'my_project' : " project_path
            if [[ ! -d "$project_path/tests" ]]; then
                echo "Erreur : le dossier 'tests' est introuvable."
            else
                cd "$project_path" || exit 1
                load_all_tests
                echo "Projet rechargé."
            fi
            ;;
        5)
            echo "Au revoir !"
            exit 0
            ;;
        6)
            display_all_tests
            ;;
        7)
            for file in "${test_files[@]}"; do
                echo ""
                echo "Fichier : $file"
                tmp_file="${file}.tmp"
                limite=20

                while true; do
                    echo "Entrez le nombre de pions (entre 1 et $limite) pour ce fichier :"
                    read nb

                    if ! [[ "$nb" =~ ^[0-9]+$ ]]; then
                        echo "Erreur : entrez un nombre entier."
                    elif [ "$nb" -lt 1 ] || [ "$nb" -gt "$limite" ]; then
                        echo "Erreur : le nombre doit être entre 1 et $limite."
                    else
                        break
                    fi
                done

                echo "Latitude du centre :"
                read lat
                echo "Longitude du centre :"
                read lon

                ligne=$(python3 gen_ligne_robot.py "$nb" "$lat" "$lon")

                if [ -z "$ligne" ]; then
                    echo "Erreur : la ligne générée est vide. On saute ce fichier."
                    continue
                fi

                > "$tmp_file"
                while IFS= read -r line || [[ -n "$line" ]]; do
                    if [[ "$line" == *"création mission custom"* ]]; then
                        echo -e "\t$ligne" >> "$tmp_file"
                    else
                        echo "$line" >> "$tmp_file"
                    fi
                done < "$file"

                cp "$file" "${file}.bak"
                mv "$tmp_file" "$file"
                echo "Ligne insérée dans $file (sauvegarde : ${file}.bak)"
            done
            ;;
        *)
            echo "Choix invalide."
            ;;
    esac
done
