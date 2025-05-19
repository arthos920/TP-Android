1)
    echo "Sous-dossiers disponibles dans 'tests/' :"
    subfolders=()
    while IFS= read -r -d $'\0' dir; do
        subfolders+=("${dir#./}")  # on enlève le "./" du début
    done < <(find tests -mindepth 1 -maxdepth 1 -type d -print0)

    selected_subfolders=()
    select folder in "${subfolders[@]}"; do
        if [[ -n "$folder" ]]; then
            selected_subfolders+=("$folder")
            echo "$folder ajouté."
            read -p "Ajouter un autre sous-dossier ? (y/n) : " rep
            if [[ "$rep" != "y" ]]; then
                break
            fi
        else
            echo "Sélection invalide."
        fi
    done

    # Lancement des tests sur les dossiers sélectionnés
    if [ ${#selected_subfolders[@]} -eq 0 ]; then
        echo "Aucun sous-dossier sélectionné."
    else
        cmd="robot --pythonpath ."
        for folder in "${selected_subfolders[@]}"; do
            cmd+=" \"$folder\""
        done
        echo "Commande : $cmd"
        eval "$cmd"
    fi
    ;;
