from __future__ import annotations

import os
import httpx
import asyncio
from dataclasses import dataclass
from typing import List, Dict, Optional

from openai import OpenAI, AsyncOpenAI


# -------------------------
# 0) Client (comme toi)
# -------------------------
proxy = httpx.Proxy(url="xxxx")

client = OpenAI(
    api_key="xxx",
    base_url="xxx/api/v1",
    http_client=httpx.Client(proxy=proxy, verify=False, follow_redirects=False),
)

# Pour l'async
async_client = AsyncOpenAI(
    api_key="xxx",
    base_url="xxx/api/v1",
    http_client=httpx.AsyncClient(proxy=proxy, verify=False, follow_redirects=False),
)

Message = Dict[str, str]


# -------------------------
# 1) Config + helpers
# -------------------------
@dataclass
class DuelConfig:
    turns: int = 5
    temperature: float = 0.7
    max_tokens: int = 300

    # Anti-explosion: garde N derniers messages non-system
    max_history_messages: int = 12

    # Stops
    stop_on_repeat: bool = True
    stop_on_too_long_words: Optional[int] = 500  # None pour désactiver


def _trim_history(messages: List[Message], max_history_messages: int) -> List[Message]:
    """Conserve tous les system + seulement les N derniers messages non-system."""
    system_msgs = [m for m in messages if m["role"] == "system"]
    other_msgs = [m for m in messages if m["role"] != "system"]
    if max_history_messages is not None and len(other_msgs) > max_history_messages:
        other_msgs = other_msgs[-max_history_messages:]
    return system_msgs + other_msgs


def _extract_text(resp) -> str:
    return (resp.choices[0].message.content or "").strip()


def _print_block(title: str, text: str):
    print(f"\n{title}\n{text}\n")


def _should_stop(text: str, last_text: Optional[str], cfg: DuelConfig) -> Optional[str]:
    if cfg.stop_on_repeat and last_text is not None and text.strip() == last_text.strip():
        return "répétition détectée"

    if cfg.stop_on_too_long_words is not None:
        if len(text.split()) > cfg.stop_on_too_long_words:
            return f"réponse trop longue (> {cfg.stop_on_too_long_words} mots)"

    return None


# =========================================================
# 2) SYNC (non-streaming) : duel propre + system prompts
# =========================================================
def chat_between_models(
    client: OpenAI,
    model_a: str,
    model_b: str,
    prompt: str,
    turns: int = 5,
    system_a: str = "Tu es A: rationnel, structuré, concis.",
    system_b: str = "Tu es B: contradicteur intelligent, propose des contre-exemples.",
    temperature: float = 0.7,
    max_tokens: int = 300,
    max_history_messages: int = 12,
    verbose: bool = True,
) -> List[Message]:
    """
    Version améliorée de TA fonction (même nom / mêmes params principaux).
    - Ajoute system prompts
    - Pas de faux messages user
    - Historique tronqué
    - Stop conditions
    """
    cfg = DuelConfig(
        turns=turns,
        temperature=temperature,
        max_tokens=max_tokens,
        max_history_messages=max_history_messages,
    )

    messages: List[Message] = [
        {"role": "system", "content": system_a},
        {"role": "system", "content": system_b},
        {"role": "user", "content": prompt},
    ]

    last_text: Optional[str] = None

    for i in range(cfg.turns):
        for label, model in (("🅰️ Modèle A", model_a), ("🅱️ Modèle B", model_b)):
            messages = _trim_history(messages, cfg.max_history_messages)

            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

            text = _extract_text(resp)

            if verbose:
                _print_block(f"{label} | Tour {i+1} | {model}", text)

            reason = _should_stop(text, last_text, cfg)
            if reason:
                if verbose:
                    print(f"⚠️ Stop: {reason}")
                return messages

            last_text = text
            messages.append({"role": "assistant", "content": text})

    return messages


# =========================================================
# 3) SYNC + STREAMING (affichage en direct)
# =========================================================
def _stream_text_sync(stream) -> str:
    chunks: List[str] = []
    for chunk in stream:
        # Format standard OpenAI-compatible: chunk.choices[0].delta.content
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            print(piece, end="", flush=True)
            chunks.append(piece)
    print()
    return "".join(chunks).strip()


def chat_between_models_streaming(
    client: OpenAI,
    model_a: str,
    model_b: str,
    prompt: str,
    turns: int = 5,
    system_a: str = "Tu es A: rationnel, structuré, concis.",
    system_b: str = "Tu es B: contradicteur intelligent, propose des contre-exemples.",
    temperature: float = 0.7,
    max_tokens: int = 300,
    max_history_messages: int = 12,
) -> List[Message]:
    cfg = DuelConfig(
        turns=turns,
        temperature=temperature,
        max_tokens=max_tokens,
        max_history_messages=max_history_messages,
    )

    messages: List[Message] = [
        {"role": "system", "content": system_a},
        {"role": "system", "content": system_b},
        {"role": "user", "content": prompt},
    ]

    last_text: Optional[str] = None

    for i in range(cfg.turns):
        for label, model in (("🅰️ Modèle A", model_a), ("🅱️ Modèle B", model_b)):
            messages = _trim_history(messages, cfg.max_history_messages)

            print(f"\n{label} | Tour {i+1} | {model} (streaming)\n", end="", flush=True)

            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

            text = _stream_text_sync(stream)

            reason = _should_stop(text, last_text, cfg)
            if reason:
                print(f"⚠️ Stop: {reason}")
                return messages

            last_text = text
            messages.append({"role": "assistant", "content": text})

    return messages


# =========================================================
# 4) ASYNC (non-streaming)
# =========================================================
async def chat_between_models_async(
    async_client: AsyncOpenAI,
    model_a: str,
    model_b: str,
    prompt: str,
    turns: int = 5,
    system_a: str = "Tu es A: rationnel, structuré, concis.",
    system_b: str = "Tu es B: contradicteur intelligent, propose des contre-exemples.",
    temperature: float = 0.7,
    max_tokens: int = 300,
    max_history_messages: int = 12,
    verbose: bool = True,
) -> List[Message]:
    cfg = DuelConfig(
        turns=turns,
        temperature=temperature,
        max_tokens=max_tokens,
        max_history_messages=max_history_messages,
    )

    messages: List[Message] = [
        {"role": "system", "content": system_a},
        {"role": "system", "content": system_b},
        {"role": "user", "content": prompt},
    ]

    last_text: Optional[str] = None

    for i in range(cfg.turns):
        for label, model in (("🅰️ Modèle A", model_a), ("🅱️ Modèle B", model_b)):
            messages = _trim_history(messages, cfg.max_history_messages)

            resp = await async_client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

            text = _extract_text(resp)

            if verbose:
                _print_block(f"{label} | Tour {i+1} | {model}", text)

            reason = _should_stop(text, last_text, cfg)
            if reason:
                if verbose:
                    print(f"⚠️ Stop: {reason}")
                return messages

            last_text = text
            messages.append({"role": "assistant", "content": text})

    return messages


# =========================================================
# 5) ASYNC + STREAMING
# =========================================================
async def _stream_text_async(stream) -> str:
    chunks: List[str] = []
    async for chunk in stream:
        delta = chunk.choices[0].delta
        piece = getattr(delta, "content", None)
        if piece:
            print(piece, end="", flush=True)
            chunks.append(piece)
    print()
    return "".join(chunks).strip()


async def chat_between_models_streaming_async(
    async_client: AsyncOpenAI,
    model_a: str,
    model_b: str,
    prompt: str,
    turns: int = 5,
    system_a: str = "Tu es A: rationnel, structuré, concis.",
    system_b: str = "Tu es B: contradicteur intelligent, propose des contre-exemples.",
    temperature: float = 0.7,
    max_tokens: int = 300,
    max_history_messages: int = 12,
) -> List[Message]:
    cfg = DuelConfig(
        turns=turns,
        temperature=temperature,
        max_tokens=max_tokens,
        max_history_messages=max_history_messages,
    )

    messages: List[Message] = [
        {"role": "system", "content": system_a},
        {"role": "system", "content": system_b},
        {"role": "user", "content": prompt},
    ]

    last_text: Optional[str] = None

    for i in range(cfg.turns):
        for label, model in (("🅰️ Modèle A", model_a), ("🅱️ Modèle B", model_b)):
            messages = _trim_history(messages, cfg.max_history_messages)

            print(f"\n{label} | Tour {i+1} | {model} (async streaming)\n", end="", flush=True)

            stream = await async_client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=cfg.temperature,
                max_tokens=cfg.max_tokens,
            )

            text = await _stream_text_async(stream)

            reason = _should_stop(text, last_text, cfg)
            if reason:
                print(f"⚠️ Stop: {reason}")
                return messages

            last_text = text
            messages.append({"role": "assistant", "content": text})

    return messages


# -------------------------
# 6) Exemple d'utilisation
# -------------------------
if __name__ == "__main__":
    # System prompts (tu peux les rendre plus “personas”)
    SYSTEM_A = "Tu es le Modèle A: très logique, tu réponds en 5 points max."
    SYSTEM_B = "Tu es le Modèle B: tu challenges les affirmations, tu donnes des contre-exemples."

    # SYNC classique
    final_history = chat_between_models(
        client=client,
        model_a="magistral-2509",
        model_b="magistral-2509",
        prompt="Est-tu une IA ?",
        turns=5,
        system_a=SYSTEM_A,
        system_b=SYSTEM_B,
        temperature=0.4,
        max_tokens=250,
        max_history_messages=10,
        verbose=True,
    )

    # STREAMING sync
    # final_history = chat_between_models_streaming(
    #     client=client,
    #     model_a="magistral-2509",
    #     model_b="magistral-2509",
    #     prompt="Faites un débat court: IA consciente ou pas ?",
    #     turns=5,
    #     system_a=SYSTEM_A,
    #     system_b=SYSTEM_B,
    #     temperature=0.4,
    #     max_tokens=250,
    #     max_history_messages=10,
    # )

    # ASYNC (plus rapide si tu lances plusieurs duels en parallèle)
    # final_history = asyncio.run(chat_between_models_async(
    #     async_client=async_client,
    #     model_a="magistral-2509",
    #     model_b="magistral-2509",
    #     prompt="Est-tu une IA ?",
    #     turns=5,
    #     system_a=SYSTEM_A,
    #     system_b=SYSTEM_B,
    #     temperature=0.4,
    #     max_tokens=250,
    #     max_history_messages=10,
    # ))

    # ASYNC + STREAMING
    # final_history = asyncio.run(chat_between_models_streaming_async(
    #     async_client=async_client,
    #     model_a="magistral-2509",
    #     model_b="magistral-2509",
    #     prompt="Débat: IA et conscience (court).",
    #     turns=5,
    #     system_a=SYSTEM_A,
    #     system_b=SYSTEM_B,
    #     temperature=0.4,
    #     max_tokens=250,
    #     max_history_messages=10,
    # ))