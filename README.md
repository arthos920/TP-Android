#!/bin/bash

# Définir le chemin du fichier .robot directement dans le script
fichier="fichier.robot"

# Vérifier si le fichier existe
if [[ ! -f "$fichier" ]]; then
    echo "Le fichier $fichier n'existe pas."
    exit 1
fi

# Extraire les noms de tests et leurs tags associés
declare -A test_tags

# Variables pour gérer l'état
inside_test_section=0  # Pour savoir si nous sommes dans une section "Test Cases"
test_name=""
tags=""

# Lire le fichier ligne par ligne et traiter les tests et tags
while IFS= read -r line; do
    # Si on trouve une section de tests "Test Cases", on passe à l'état suivant
    if [[ "$line" =~ \*\*\* Test Cases \*\*\* ]]; then
        inside_test_section=1
        continue
    fi

    # Si on est dans une section "Test Cases", récupérer le nom du test
    if [[ "$inside_test_section" -eq 1 ]]; then
        # Si la ligne contient un nom de test
        if [[ "$line" =~ ^[[:space:]]*[a-zA-Z0-9_]+ ]]; then
            test_name=$(echo "$line" | sed 's/^[[:space:]]*//')  # Enlever les espaces avant le nom du test
            tags=""  # Réinitialiser les tags pour chaque test
        fi

        # Si la ligne contient des tags, mémoriser les tags
        if [[ "$line" =~ ^[[:space:]]*\[Tags\] ]]; then
            tags=$(echo "$line" | sed 's/^[[:space:]]*\[Tags\][[:space:]]*//')  # Enlever "[Tags]" et les espaces
            test_tags["$test_name"]="$tags"  # Associer les tags au test
            inside_test_section=0  # Sortir immédiatement de la section du test
        fi
    fi
done < "$fichier"

# Vérifier que des tests ont été trouvés
if [ ${#test_tags[@]} -eq 0 ]; then
    echo "Aucun test ou tag trouvé dans le fichier."
    exit 1
fi

# Afficher les tests et leurs tags associés
for test in "${!test_tags[@]}"; do
    echo "Test: $test, Tags: ${test_tags[$test]}"
done

# Afficher les options disponibles
echo "Que voulez-vous faire ?"
echo "1. Exécuter tous les tests"
echo "2. Sélectionner un test spécifique"
echo "3. Sélectionner plusieurs tests spécifiques"
read -p "Votre choix (1, 2 ou 3) : " choix

# Fonction pour exécuter les tests sélectionnés avec les tags
run_tests() {
    local tests_to_run="$1"  # Premier paramètre : -i $test ou -i $test1 -i $test2
    local fichier="$2"        # Deuxième paramètre : le chemin du fichier .robot

    if [ -z "$tests_to_run" ]; then
        echo "Aucun test sélectionné."
        exit 1
    fi

    # Lancer les tests avec l'option -i et les tests sélectionnés
    python3.6 -m robot $tests_to_run "$fichier"
}

case $choix in
    1)
        # Exécuter tous les tests
        echo "Exécution de tous les tests..."
        run_tests "" "$fichier"
        ;;
    2)
        # Sélectionner un test spécifique
        echo "Voici la liste des tests disponibles :"
        PS3="Sélectionnez un test: "
        select test in "${!test_tags[@]}"; do
            if [ -n "$test" ]; then
                tags="${test_tags[$test]}"
                echo "Vous avez sélectionné : $test avec tags $tags"
                run_tests "-i $tags" "$fichier"
                break
            else
                echo "Sélection invalide, veuillez essayer à nouveau."
            fi
        done
        ;;
    3)
        # Sélectionner plusieurs tests spécifiques
        echo "Voici la liste des tests disponibles :"
        selected_tests=""
        PS3="Sélectionnez un test: "
        select test in "${!test_tags[@]}"; do
            if [ -n "$test" ]; then
                tags="${test_tags[$test]}"
                selected_tests="$selected_tests -i $tags"
                echo "Test ajouté : $test avec tags $tags"
                echo "Voulez-vous ajouter un autre test ? (y/n)"
                read response
                if [[ "$response" != "y" ]]; then
                    break
                fi
            else
                echo "Sélection invalide, veuillez essayer à nouveau."
            fi
        done
        echo "Exécution des tests sélectionnés..."
        run_tests "$selected_tests" "$fichier"
        ;;
    *)
        echo "Choix invalide. Veuillez entrer 1, 2 ou 3."
        exit 1
        ;;
esac
