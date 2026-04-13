def build_gitlab_messages_for_step(
    step: int,
    *,
    project_id: str,
    ref: str,
    jira_summary: Optional[str] = None,
    tree_preview: Optional[List[str]] = None,
    ranked_files: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, List[Dict[str, str]]]:

    if step == 1:
        return "get_project", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_project.",
            },
            {
                "role": "user",
                "content": f"Appelle get_project avec project_id='{project_id}'.",
            },
        ]

    if step == 2:
        return "get_repository_tree", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_repository_tree.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_repository_tree avec project_id='{project_id}', "
                    f"ref='{ref}', path='', recursive=true."
                ),
            },
        ]

    # private_call keywords
    if step == 3:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/private_call.robot'."
                ),
            },
        ]

    # video_call keywords
    if step == 4:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/video_call.robot'."
                ),
            },
        ]

    # conference_call keywords
    if step == 5:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/conference_call.robot'."
                ),
            },
        ]

    # group_call keywords
    if step == 6:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/group_call.robot'."
                ),
            },
        ]

    # incoming_call
    if step == 7:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/incoming_call.robot'."
                ),
            },
        ]

    # outgoing_call
    if step == 8:
        return "get_file_contents", [
            {
                "role": "system",
                "content": "Tu dois appeler EXACTEMENT le tool get_file_contents.",
            },
            {
                "role": "user",
                "content": (
                    f"Appelle get_file_contents avec project_id='{project_id}', "
                    f"ref='{ref}', file_path='keywords/outgoing_call.robot'."
                ),
            },
        ]

    raise ValueError("step inconnu")





async def gitlab_run_step_forced_one_tool(
    llm,
    mcp,
    openai_tools,
    *,
    step: int,
    project_id: str,
    ref: str,
):
    # 1. Build prompt + tool attendu
    expected_tool, messages = build_gitlab_messages_for_step(
        step,
        project_id=project_id,
        ref=ref,
    )

    # 2. Appel LLM
    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=messages,
        tools=openai_tools,
        tool_choice="auto",   # le modèle doit appeler un tool
        temperature=0.0,
    )

    msg = resp.choices[0].message

    # 3. Vérifier qu’un tool est appelé
    if not msg.tool_calls:
        raise RuntimeError(f"Step {step}: aucun tool_call généré")

    tc = msg.tool_calls[0]
    name = tc.function.name
    args = json.loads(tc.function.arguments or "{}")

    print(f"[STEP {step}] TOOL_CALL -> {name} args={args}")

    # 4. Vérifier que c’est le bon tool
    if name != expected_tool:
        raise RuntimeError(
            f"Step {step}: mauvais tool appelé ({name}) au lieu de {expected_tool}"
        )

    # 5. Exécuter le tool MCP
    try:
        result = await mcp.call_tool(name, args)
        norm = normalize(result)
    except Exception as e:
        print(f"[STEP {step}] ERROR: {e}")
        raise

    return {
        "step": step,
        "tool": name,
        "args": args,
        "result": norm,
    }





TEST_TYPES = {
    "private_call",
    "video_call",
    "conference_call",
    "group_call",
    "incoming_call",
    "outgoing_call",
    "unknown",
}

TEST_TYPE_TO_STEPS = {
    "private_call": [3],
    "video_call": [4],
    "conference_call": [5],
    "group_call": [6],
    "incoming_call": [7],
    "outgoing_call": [8],
    "unknown": [3, 4, 5],
}



---------/-

async def classify_jira_test_type(llm, jira_summary: str) -> Dict[str, Any]:
    system = (
        "Tu es un classificateur de tickets Jira pour tests Robot Framework.\n"
        "À partir du résumé du ticket, détermine le type de test parmi cette liste fermée:\n"
        "- private_call\n"
        "- video_call\n"
        "- conference_call\n"
        "- group_call\n"
        "- incoming_call\n"
        "- outgoing_call\n"
        "- unknown\n\n"
        "Réponds UNIQUEMENT avec un JSON valide de cette forme:\n"
        "{\n"
        '  "test_type": "private_call|video_call|conference_call|group_call|incoming_call|outgoing_call|unknown",\n'
        '  "confidence": 0.0,\n'
        '  "reason": "explication courte"\n'
        "}\n"
        "Ne mets aucun markdown."
    )

    user = f"Résumé Jira:\n{jira_summary}"

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.0,
        max_tokens=300,
    )

    content = (resp.choices[0].message.content or "").strip()

    try:
        data = json.loads(content)
    except Exception:
        data = {
            "test_type": "unknown",
            "confidence": 0.0,
            "reason": f"JSON non parsable: {content[:300]}",
        }

    test_type = data.get("test_type", "unknown")
    if test_type not in TEST_TYPES:
        data["test_type"] = "unknown"

    try:
        data["confidence"] = float(data.get("confidence", 0.0))
    except Exception:
        data["confidence"] = 0.0

    data["reason"] = str(data.get("reason", ""))

    return data


def select_gitlab_steps_from_test_type(test_type: str) -> List[int]:
    return TEST_TYPE_TO_STEPS.get(test_type, TEST_TYPE_TO_STEPS["unknown"])



async def run_selected_gitlab_steps(
    llm,
    gitlab,
    openai_tools,
    *,
    selected_steps: List[int],
    project_id: str,
    ref: str,
) -> List[Dict[str, Any]]:
    results = []

    for step_id in selected_steps:
        try:
            res = await gitlab_run_step_forced_one_tool(
                llm,
                gitlab,
                openai_tools,
                step=step_id,
                project_id=project_id,
                ref=ref,
            )
            results.append(
                {
                    "step": step_id,
                    "ok": True,
                    "result": res,
                }
            )
        except Exception as e:
            print(f"[WARN] Step {step_id} failed: {e}")
            results.append(
                {
                    "step": step_id,
                    "ok": False,
                    "error": str(e),
                }
            )

    return results



async def recommend_keywords_from_selected_steps(
    llm,
    *,
    jira_summary: str,
    jira_classification: Dict[str, Any],
    gitlab_results: List[Dict[str, Any]],
) -> str:
    system = (
        "Tu es un expert Robot Framework.\n"
        "À partir:\n"
        "- du résumé Jira\n"
        "- du type de test détecté\n"
        "- des fichiers GitLab lus\n\n"
        "Tu dois produire une sortie claire et exploitable:\n"
        "1) Type de test retenu\n"
        "2) Pourquoi ce type a été choisi\n"
        "3) Quels fichiers du framework sont pertinents\n"
        "4) Quels keywords/fonctions semblent devoir être réutilisés\n"
        "5) Quel squelette de test Robot écrire\n"
        "6) Quelles lectures supplémentaires seraient utiles ensuite\n"
    )

    payload = {
        "jira_summary": jira_summary,
        "jira_classification": jira_classification,
        "gitlab_results": gitlab_results,
    }

    resp = await llm.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ],
        temperature=0.2,
        max_tokens=1200,
    )

    return (resp.choices[0].message.content or "").strip()






# ------------------------------------------------------------------
# Classification Jira -> type de test
# ------------------------------------------------------------------
jira_classification = await classify_jira_test_type(
    llm,
    jira_part["issue_summary"],
)

test_type = jira_classification["test_type"]
selected_steps = select_gitlab_steps_from_test_type(test_type)

print("\n=== JIRA CLASSIFICATION ===\n")
print(json.dumps(jira_classification, ensure_ascii=False, indent=2))
print("Steps sélectionnés:", selected_steps)







transport_cm, gitlab = await open_mcp(GITLAB_MCP_URL)
print("\n=== reading targeted code on gitlab ===\n")

try:
    tools_resp = await gitlab.list_tools()
    openai_tools = mcp_tools_to_openai(tools_resp)
    tool_names = [t["function"]["name"] for t in openai_tools]

    # Vérif minimale
    for required in ("get_project", "get_file_contents"):
        if required not in tool_names:
            raise RuntimeError(f"Tool GitLab manquant: {required}")

    # Step 1 et 2 si tu veux toujours récupérer projet + tree global
    project_res = await gitlab_run_step_forced_one_tool(
        llm,
        gitlab,
        openai_tools,
        step=1,
        project_id=PROJECT_ID,
        ref=GITLAB_REF,
    )

    tree_res = await gitlab_run_step_forced_one_tool(
        llm,
        gitlab,
        openai_tools,
        step=2,
        project_id=PROJECT_ID,
        ref=GITLAB_REF,
    )

    # Steps ciblés selon le type de ticket
    targeted_results = await run_selected_gitlab_steps(
        llm,
        gitlab,
        openai_tools,
        selected_steps=selected_steps,
        project_id=PROJECT_ID,
        ref=GITLAB_REF,
    )

    print("\n=== TARGETED GITLAB RESULTS ===\n")
    for item in targeted_results:
        if item["ok"]:
            print(f"[OK] step={item['step']}")
        else:
            print(f"[WARN] step={item['step']} failed -> {item['error']}")

    # Synthèse ciblée
    targeted_reco = await recommend_keywords_from_selected_steps(
        llm,
        jira_summary=jira_part["issue_summary"],
        jira_classification=jira_classification,
        gitlab_results=targeted_results,
    )

    print("\n=== TARGETED RECOMMENDATIONS ===\n")
    print(targeted_reco)

finally:
    try:
        await gitlab.__aexit__(None, None, None)
    except Exception:
        pass
    try:
        await transport_cm.__aexit__(None, None, None)
    except Exception:
        pass




