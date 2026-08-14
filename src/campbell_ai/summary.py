"""AI-generated titles for archived conversations.

The conversation list needs a label. The first user message always works and is free of
invention, so it is the default and the fallback. But a first message like "hola, tengo
una duda" says nothing about a thread that turned into a root-cause analysis, so once a
conversation has a few exchanges a short summary is generated and preferred.

Two constraints follow from the grounding rule that applies to every Campbell AI
answer: the summary must not introduce a number, unit, date or identifier that is not
already in the conversation, and a failure to produce one is never an error — the
deterministic title stands.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Sequence

from src.campbell_ai.models import ConversationMessage


logger = logging.getLogger("campbell_ai.summary")


SUMMARY_INSTRUCTIONS = """Eres un titulador de conversaciones de mantenimiento predictivo.

Recibes una conversación entre un usuario y un asistente. Devuelves UN título corto que
permita reconocerla en una lista.

Reglas:
- Máximo 8 palabras, en español, sin punto final.
- Describe el tema de la conversación, no la respuesta.
- No inventes cifras, fechas, unidades ni identificadores: si un número no aparece
  literalmente en la conversación, no puede aparecer en el título.
- Prefiere no incluir números. Un título sin cifras siempre es preferible a uno con
  una cifra dudosa.
- No uses comillas, viñetas ni prefijos como "Título:".

Ejemplos de salida válida:
Alertas de temperatura en camión
Pareto de alertas por equipo
Causa raíz de alerta de refrigerante
"""

# A title only has to be recognizable; four exchanges of context is plenty and keeps the
# call cheap.
_MAX_CONTEXT_MESSAGES = 6
_MAX_CHARS_PER_MESSAGE = 400
SUMMARY_MAX_WORDS = 8


def _transcript(messages: Sequence[ConversationMessage]) -> str:
    lines = []
    for message in messages[:_MAX_CONTEXT_MESSAGES]:
        speaker = "Usuario" if message.role == "user" else "Asistente"
        text = " ".join(str(message.content).split())[:_MAX_CHARS_PER_MESSAGE]
        if text:
            lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:[.,]\d+)?", text))


def sanitize_summary(candidate: str, transcript: str) -> str:
    """Accept a candidate title only if it invents nothing.

    Enforced here rather than trusted from the prompt: the same rule that governs
    answers governs their labels, and a label is not worth a second model call to
    verify.
    """
    text = " ".join(str(candidate or "").split())
    text = text.strip().strip('"').strip("'").strip()
    text = re.sub(r"^(t[íi]tulo|resumen)\s*:\s*", "", text, flags=re.IGNORECASE).strip()
    if not text:
        return ""
    words = text.split()
    if len(words) > SUMMARY_MAX_WORDS:
        text = " ".join(words[:SUMMARY_MAX_WORDS])
    # Any figure in the title must already exist in the conversation.
    if not _numbers(text) <= _numbers(transcript):
        return ""
    return text.rstrip(".")


async def generate_conversation_summary(
    messages: Sequence[ConversationMessage], model: str
) -> str:
    """Return a short title for the thread, or "" when one cannot be produced."""
    transcript = _transcript(messages)
    if not transcript or not os.getenv("OPENAI_API_KEY"):
        return ""
    try:
        from agents import Agent, ModelSettings, Runner
    except ImportError:
        return ""

    try:
        agent = Agent(
            name="Conversation Titler",
            instructions=SUMMARY_INSTRUCTIONS,
            model=model,
            model_settings=ModelSettings(temperature=0.0),
        )
        result = await Runner.run(starting_agent=agent, input=transcript, max_turns=1)
    except Exception:
        # A missing title is cosmetic; the first message already labels the thread.
        logger.info("Campbell AI no pudo generar el resumen de la conversación")
        return ""
    return sanitize_summary(str(getattr(result, "final_output", "") or ""), transcript)
