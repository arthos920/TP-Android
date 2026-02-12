from typing import Tuple, List, Dict, Optional

def build_gitlab_messages_for_step(
    step: int,
    *,
    project_id: str,
    ref: str,
    jira_summary: Optional[str] = None,
    tree_preview: Optional[List[str]] = None,
) -> Tuple[str, List[Dict[str, str]]]:
    """
    Retourne: (expected_tool_name OR "TOOL_LOOP", messages)
    - step 1/2/3 => expected tool unique
    - step 4     => "TOOL_LOOP" (le modèle peut appeler plusieurs tools autorisés)
    """

    if step == 1:
        tool = "get_project"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_project avec l'argument project_id (string). "
                    "Ne fais rien d'autre."
                ),
            },
            {"role": "user", "content": f"Appelle get_project avec project_id='{project_id}'."},
        ]
        return tool, messages

    if step == 2:
        tool = "get_repository_tree"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_repository_tree.\n"
                    "Arguments requis:\n"
                    "- project_id (string)\n"
                    "- ref (string)\n"
                    "- path (string) -> utilise ''\n"
                    "- recursive (boolean) -> true\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_repository_tree avec project_id='{project_id}', ref='{ref}', "
                    "path='', recursive=true."
                ),
            },
        ]
        return tool, messages

    if step == 3:
        tool = "get_file_contents"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu dois appeler EXACTEMENT le tool get_file_contents.\n"
                    "Arguments requis:\n"
                    "- project_id (string)\n"
                    "- ref (string)\n"
                    "- file_path (string)\n"
                    "Lis EN PRIORITÉ doc/convention.md. "
                    "Si doc/convention.md n'existe pas, tente docs/convention.md puis convention.md.\n"
                    "Ne fais rien d'autre."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Lis le fichier des conventions. Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='doc/convention.md'. "
                    "Si ça échoue, essaye docs/convention.md puis convention.md."
                ),
            },
        ]
        return tool, messages

    if step == 4:
        # step 4 = TOOL LOOP multi-tools, guidé par jira_summary + tree_preview
        if not jira_summary:
            jira_summary = "(résumé Jira manquant)"

        tree_hint_txt = ""
        if tree_preview:
            tree_hint_txt = (
                "\nAperçu du tree (extrait):\n- " + "\n- ".join(tree_preview[:80]) + "\n"
            )

        tool = "TOOL_LOOP"
        messages = [
            {
                "role": "system",
                "content": (
                    "Tu es un agent GitLab pour analyser un framework Robot Framework.\n"
                    "Tu peux appeler plusieurs fois (autant que nécessaire) UNIQUEMENT ces tools:\n"
                    "- get_project\n"
                    "- get_repository_tree\n"
                    "- get_file_contents\n\n"
                    "Objectif:\n"
                    "1) À partir du résumé Jira, déterminer quels fichiers du repo sont pertinents "
                    "pour générer un nouveau test Robot (.robot).\n"
                    "2) Explorer le repo (tree) et lire les fichiers clés (conventions, resources, exemples de tests).\n"
                    "3) Sortir une synthèse finale (sans tool_call) avec:\n"
                    "   - Fichiers lus (liste)\n"
                    "   - Architecture (dossiers)\n"
                    "   - Conventions (tags, naming, setup/teardown, resources/imports)\n"
                    "   - Keywords/Librairies à réutiliser\n"
                    "   - Fichiers “templates” (tests proches à copier)\n\n"
                    "Contraintes importantes:\n"
                    "- N'invente pas des paths: utilise d'abord get_repository_tree si besoin.\n"
                    "- Pour lire un fichier: get_file_contents(project_id, ref, file_path='...') "
                    "(ATTENTION: le paramètre s'appelle file_path, pas path).\n"
                    "- Tu peux relancer get_repository_tree sur un sous-dossier (path='tests', 'resources', etc.) "
                    "si tu as besoin de réduire le bruit.\n"
                    "- À la fin, tu dois répondre avec une synthèse finale et ne plus appeler d'outil."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Résumé Jira:\n{jira_summary}\n\n"
                    f"Repo:\n- project_id='{project_id}'\n- ref='{ref}'\n"
                    f"{tree_hint_txt}\n"
                    "Maintenant, analyse le repo en lisant les fichiers pertinents. "
                    "Tu peux appeler get_repository_tree et get_file_contents autant que nécessaire. "
                    "Termine par une synthèse finale exploitable pour générer une feuille Robot."
                ),
            },
        ]
        return tool, messages

    raise ValueError("step doit être 1,2,3 ou 4.")




async def gitlab_run_step4_tool_loop(
    llm: AsyncOpenAI,
    gitlab: ClientSession,
    openai_tools: List[Dict[str, Any]],
    *,
    project_id: str,
    ref: str,
    jira_summary: str,
    tree_preview: Optional[List[str]] = None,
    max_steps: int = 18,
) -> Dict[str, Any]:
    expected_tool, messages = build_gitlab_messages_for_step(
        4,
        project_id=project_id,
        ref=ref,
        jira_summary=jira_summary,
        tree_preview=tree_preview,
    )
    assert expected_tool == "TOOL_LOOP"

    allowed_tools = {"get_project", "get_repository_tree", "get_file_contents"}
    traces: List[Dict[str, Any]] = []

    for i in range(1, max_steps + 1):
        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            temperature=0.0,
        )

        msg = resp.choices[0].message

        # Si réponse finale
        if not msg.tool_calls:
            final_text = msg.content or ""
            messages.append({"role": "assistant", "content": final_text})
            files_read = []
            for t in traces:
                if t["tool"] == "get_file_contents":
                    fp = t["args"].get("file_path")
                    if fp:
                        files_read.append(fp)
            return {
                "final_synthesis": final_text,
                "tool_traces": traces,
                "files_read": files_read,
            }

        # Ajoute assistant intermédiaire
        messages.append({"role": "assistant", "content": msg.content or ""})

        # Exécute tous les tool_calls
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")

            if name not in allowed_tools:
                raise RuntimeError(f"[STEP4] Tool non autorisé: {name}")

            print(f"\n[STEP4] TOOL_CALL loop={i} -> {name} args={args}")
            result = await gitlab.call_tool(name, args)
            norm = normalize(result)
            traces.append({"loop": i, "tool": name, "args": args, "result": norm})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(norm, ensure_ascii=False),
                }
            )

    raise RuntimeError(f"[STEP4] max_steps atteint ({max_steps}).")


# step1/2/3
project_res = await gitlab_run_step_forced_one_tool(
    llm, gitlab, openai_tools, step=1, project_id=PROJECT_ID, ref=GITLAB_REF
)

tree_res = await gitlab_run_step_forced_one_tool(
    llm, gitlab, openai_tools, step=2, project_id=PROJECT_ID, ref=GITLAB_REF
)

conv_res = await gitlab_run_step_forced_one_tool(
    llm, gitlab, openai_tools, step=3, project_id=PROJECT_ID, ref=GITLAB_REF
)

# petit preview pour aider step4 (optionnel)
tree_norm = normalize(tree_res["result"])
tree_preview = []
if isinstance(tree_norm, list):
    for it in tree_norm[:120]:
        if isinstance(it, dict) and "path" in it:
            tree_preview.append(it["path"])
elif isinstance(tree_norm, dict):
    # adapte si ton MCP renvoie autre structure
    pass

# step4 = tool loop multi tools
step4_res = await gitlab_run_step4_tool_loop(
    llm,
    gitlab,
    openai_tools,
    project_id=PROJECT_ID,
    ref=GITLAB_REF,
    jira_summary=jira_summary_text,   # <- résumé Jira que tu ajoutes
    tree_preview=tree_preview,
    max_steps=20,
)

print("\n=== STEP4 SYNTHÈSE ===\n")
print(step4_res["final_synthesis"])
print("\nFichiers lus:")
for f in step4_res["files_read"]:
    print(" -", f)