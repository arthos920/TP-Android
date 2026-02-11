plan_text = (resp.choices[0].message.content or "").strip()

print("\n=== PLAN JSON (raw) ===\n", plan_text[:1000], "\n")

if not plan_text:
    raise RuntimeError(
        "Le modèle n’a renvoyé aucun texte pour le plan JSON.\n"
        "Vérifie qu’il n’a pas fait un tool_call ou que max_tokens est suffisant."
    )

# --- Extraction JSON robuste ---
def extract_json(text: str) -> dict:
    text = text.strip()

    # 1️⃣ JSON direct
    try:
        return json.loads(text)
    except Exception:
        pass

    # 2️⃣ Markdown ```json
    import re
    m = re.search(r"```json(.*?)```", text, re.S)
    if m:
        return json.loads(m.group(1).strip())

    # 3️⃣ Premier objet JSON trouvé
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        return json.loads(m.group(0))

    raise RuntimeError("Impossible d’extraire un JSON valide du plan.")

plan = extract_json(plan_text)

print("PLAN JSON PARSE OK ✔\n")