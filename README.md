async def gitlab_run_step4_tool_loop(
    llm,
    gitlab,
    openai_tools,
    *,
    project_id: str,
    ref: str,
    jira_summary: str,
    tree_preview=None,
    max_steps: int = 18,
):
    expected_tool, messages = build_gitlab_messages_for_step(
        4,
        project_id=project_id,
        ref=ref,
        jira_summary=jira_summary,
        tree_preview=tree_preview,
    )

    allowed_tools = {
        "get_project",
        "get_repository_tree",
        "get_file_contents",
    }

    traces = []

    # 🔒 Anti-boucle mémoire appels
    seen_calls = set()

    for i in range(1, max_steps + 1):

        resp = await llm.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=openai_tools,
            tool_choice="auto",
            temperature=0.0,
        )

        msg = resp.choices[0].message

        # -----------------------------
        # FIN → synthèse finale
        # -----------------------------
        if not msg.tool_calls:
            final_text = msg.content or ""
            messages.append({"role": "assistant", "content": final_text})

            files_read = [
                t["args"].get("file_path")
                for t in traces
                if t["tool"] == "get_file_contents"
                and t["args"].get("file_path")
            ]

            return {
                "final_synthesis": final_text,
                "tool_traces": traces,
                "files_read": files_read,
            }

        messages.append({"role": "assistant", "content": msg.content or ""})

        # -----------------------------
        # EXEC TOOL CALLS
        # -----------------------------
        for tc in msg.tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")

            if name not in allowed_tools:
                raise RuntimeError(f"[STEP4] Tool non autorisé: {name}")

            # ==========================================
            # 🔒 ANTI DUPLICATE CALL (BONUS)
            # ==========================================
            call_sig = (
                name,
                json.dumps(args, sort_keys=True),
            )

            if call_sig in seen_calls:
                print(f"[STEP4] ⏭️ Skip duplicate call -> {name} {args}")
                continue

            seen_calls.add(call_sig)

            print(f"\n[STEP4] TOOL_CALL loop={i} -> {name} args={args}")

            # =============================
            # SAFE EXECUTION
            # =============================
            try:
                result = await gitlab.call_tool(name, args)
                norm = normalize(result)
                tool_error = None

            except Exception as e:
                print(f"[STEP4][WARN] Tool failed: {name} -> {e}")

                norm = {
                    "error": True,
                    "tool": name,
                    "message": str(e),
                    "args": args,
                }

                tool_error = str(e)

            traces.append(
                {
                    "loop": i,
                    "tool": name,
                    "args": args,
                    "error": tool_error,
                    "result": norm,
                }
            )

            # 🔁 Retour au LLM même si erreur
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "name": name,
                    "content": json.dumps(norm, ensure_ascii=False),
                }
            )

    raise RuntimeError(f"[STEP4] max_steps atteint ({max_steps})")