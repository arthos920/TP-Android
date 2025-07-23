from openpyxl import load_workbook
from openpyxl.styles import PatternFill

def color_status(file_path, test_value, color):
    # Chargement du fichier Excel
    wb = load_workbook(file_path)
    ws = wb.active

    # Définir les couleurs vert et rouge
    green_fill = PatternFill(start_color="00FF00", end_color="00FF00", fill_type="solid")
    red_fill = PatternFill(start_color="FF0000", end_color="FF0000", fill_type="solid")

    # Parcourir les lignes (à partir de la ligne 2 pour éviter l'en-tête)
    for row in ws.iter_rows(min_row=2):
        test_cell = row[1]      # Colonne B : test
        status_cell = row[2]    # Colonne C : status

        if test_cell.value == test_value:
            if color.lower() == "vert":
                status_cell.fill = green_fill
                status_cell.value = "PASS"
            elif color.lower() == "rouge":
                status_cell.fill = red_fill
                status_cell.value = "FAIL"
            else:
                print("Erreur : couleur non reconnue (utilise 'vert' ou 'rouge').")
            break
    else:
        print(f"Test '{test_value}' non trouvé.")

    wb.save(file_path)
    print("Fichier mis à jour avec succès.")

# Exemple :
# color_status("tests.xlsx", "Connexion utilisateur", "vert")
