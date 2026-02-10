async def _stream_text_async(stream) -> str:
    chunks = []

    async for chunk in stream:
        # Certains chunks n'ont pas de choices
        choices = getattr(chunk, "choices", None)
        if not choices:
            continue

        choice0 = choices[0]

        # Format classique: delta.content
        delta = getattr(choice0, "delta", None)
        if delta is not None:
            piece = getattr(delta, "content", None)
            if piece:
                print(piece, end="", flush=True)
                chunks.append(piece)
            continue

        # Fallback: parfois message.content
        msg = getattr(choice0, "message", None)
        if msg is not None:
            piece = getattr(msg, "content", None)
            if piece:
                print(piece, end="", flush=True)
                chunks.append(piece)
            continue

    print()
    return "".join(chunks).strip()