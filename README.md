#!/bin/bash

# Définir le chemin du fichier .robot directement dans le script
fichier="fichier.robot"

# Vérifier si le fichier existe
if [[ ! -f "$fichier" ]]; then
    echo "Le fichier $fichier n'existe pas."
    exit 1
fi

# Extraire la liste des tests
tests=$(awk '/\*\*\* Test Cases \*\*\*/ {flag=1; next} flag && /^[^ \t]+/ {print $1}' "$fichier")

# Si aucun test n'a été trouvé
if [ -z "$tests" ]; then
    echo "Aucun test trouvé dans le fichier."
    exit 1
fi

# Afficher les options disponibles
echo "Que voulez-vous faire ?"
echo "1. Exécuter tous les tests"
echo "2. Sélectionner un test spécifique"
echo "3. Sélectionner plusieurs tests spécifiques"
read -p "Votre choix (1, 2 ou 3) : " choix

# Fonction pour exécuter les tests sélectionnés
run_tests() {
    local tests_to_run="$1"
    if [ -z "$tests_to_run" ]; then
        echo "Aucun test sélectionné."
        exit 1
    fi

    # Lancer les tests
    python3.6 -m robot $tests_to_run "$fichier"
}

case $choix in
    1)
        # Exécuter tous les tests
        echo "Exécution de tous les tests..."
        run_tests ""
        ;;
    2)
        # Sélectionner un test spécifique
        echo "Voici la liste des tests disponibles :"
        select test in $tests; do
            if [ -n "$test" ]; then
                echo "Vous avez sélectionné : $test"
                run_tests "-i $test"
                break
            else
                echo "Sélection invalide, veuillez essayer à nouveau."
            fi
        done
        ;;
    3)
        # Sélectionner plusieurs tests spécifiques
        echo "Voici la liste des tests disponibles :"
        select test in $tests; do
            if [ -n "$test" ]; then
                selected_tests="$selected_tests -i $test"
                echo "Test ajouté : $test"
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
        run_tests "$selected_tests"
        ;;
    *)
        echo "Choix invalide. Veuillez entrer 1, 2 ou 3."
        exit 1
        ;;
esac
