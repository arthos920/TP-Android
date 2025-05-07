#!/bin/bash

# Définir le chemin du fichier .robot directement dans le script
fichier="fichier.robot"

# Vérifier si le fichier existe
if [[ ! -f "$fichier" ]]; then
    echo "Le fichier $fichier n'existe pas."
    exit 1
fi

# Extraire les noms de tests
tests=$(awk '/\*\*\* Test Cases \*\*\*/ {flag=1; next} flag && /^[^ \t]+/ {print $1}' "$fichier")

# Si aucun test n'a été trouvé
if [ -z "$tests" ]; then
    echo "Aucun test trouvé dans le fichier."
    exit 1
fi

# Extraire les tags et associer à chaque test
declare -A test_tags

# Parcours des tests et association des tags
while IFS= read -r test; do
    # Cherche les tags pour chaque test
    tags=$(awk -v test="$test" '/\*\*\* Test Cases \*\*\*/ {flag=1} flag && $1 == test {getline; getline; print $0}' "$fichier")
    
    # Enregistrer les tags associés au test dans un tableau associatif
    test_tags["$test"]="$tags"
done <<< "$tests"

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
