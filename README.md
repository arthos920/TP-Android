def mcp_result_to_text(result) -> str:
    """
    Convertit proprement un résultat MCP (souvent list[TextContent]) en string.
    """
    content = getattr(result, "content", result)

    # Cas fréquent: liste d'objets avec .text
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                text = getattr(item, "text", None)
                if text is not None:
                    parts.append(text)
                else:
                    # fallback
                    parts.append(str(item))
        return "\n".join(parts)

    # Déjà une string
    if isinstance(content, str):
        return content

    # dict / autre
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)