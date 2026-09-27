"""
Provider-agnostic LLM access for the copilot and advisory features.

Three providers, tried in preference order, each optional:

  anthropic  Claude via the official `anthropic` SDK. Paid; best answers.
  gemini     Google Gemini via its REST API. Free tier, no card required.
  groq       Llama on Groq via its REST API. Free tier, no card required.

If no key is configured, or every configured provider fails, callers get
`LLMUnavailable` and fall back to the deterministic, data-grounded answers in
copilot.py. The AI features therefore never block the dashboard and never
depend on a paid account.

The model is only ever asked to *phrase* what the risk engine already computed.
Every prompt carries the numbers, and the system prompt forbids introducing new
ones, so a hallucinated rainfall figure would contradict data on the same screen.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

import httpx

from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    LLM_PROVIDER,
)

log = logging.getLogger("jaldrishti.llm")


class LLMUnavailable(RuntimeError):
    """No provider configured, or all configured providers failed."""


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str


def configured_providers() -> list[str]:
    order = {"anthropic": ANTHROPIC_API_KEY, "gemini": GEMINI_API_KEY, "groq": GROQ_API_KEY}
    present = [name for name, key in order.items() if key]
    if LLM_PROVIDER in present:
        present.remove(LLM_PROVIDER)
        present.insert(0, LLM_PROVIDER)
    return present


def status() -> dict:
    return {
        "active": configured_providers(),
        "preferred": configured_providers()[0] if configured_providers() else None,
        "models": {"anthropic": ANTHROPIC_MODEL, "gemini": GEMINI_MODEL, "groq": GROQ_MODEL},
        "fallback": "deterministic, data-grounded templates (always available)",
    }


# --------------------------------------------------------------------- Claude

_anthropic_client = None


def _claude_client():
    global _anthropic_client
    if _anthropic_client is None:
        import anthropic

        _anthropic_client = anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY, timeout=90.0)
    return _anthropic_client


async def _call_anthropic(system_blocks: Sequence[str], messages: list[dict], max_tokens: int) -> LLMResult:
    import anthropic

    # The instructions are stable and the data snapshot changes only once per
    # refresh, so both go in `system` (static first) with the cache breakpoint on
    # the last block: repeated questions within a refresh hit the cache.
    system = [{"type": "text", "text": block} for block in system_blocks]
    system[-1]["cache_control"] = {"type": "ephemeral"}

    try:
        response = await _claude_client().beta.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            # Chat-style Q&A over pre-computed numbers does not need deep reasoning.
            output_config={"effort": "medium"},
            # On a policy decline, re-run on Anthropic's recommended fallback model
            # instead of returning a refusal to a flood-response operator.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("Anthropic key rejected") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("Anthropic rate limited") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"Anthropic error {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("Anthropic unreachable") from exc

    if response.stop_reason == "refusal":
        raise LLMUnavailable("Anthropic declined the request")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise LLMUnavailable("Anthropic returned no text")
    return LLMResult(text=text, provider="anthropic", model=response.model)


# --------------------------------------------------------------------- Gemini


async def _call_gemini(system_blocks: Sequence[str], messages: list[dict], max_tokens: int) -> LLMResult:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
    body = {
        "system_instruction": {"parts": [{"text": "\n\n".join(system_blocks)}]},
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, json=body, headers={"x-goog-api-key": GEMINI_API_KEY})
    if r.status_code != 200:
        raise LLMUnavailable(f"Gemini error {r.status_code}: {r.text[:160]}")
    data = r.json()
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text:
        raise LLMUnavailable("Gemini returned no text")
    return LLMResult(text=text, provider="gemini", model=GEMINI_MODEL)


# ----------------------------------------------------------------------- Groq


async def _call_groq(system_blocks: Sequence[str], messages: list[dict], max_tokens: int) -> LLMResult:
    body = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": "\n\n".join(system_blocks)}, *messages],
        "max_tokens": max_tokens,
        "temperature": 0.3,
    }
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        )
    if r.status_code != 200:
        raise LLMUnavailable(f"Groq error {r.status_code}: {r.text[:160]}")
    choices = r.json().get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "").strip() if choices else ""
    if not text:
        raise LLMUnavailable("Groq returned no text")
    return LLMResult(text=text, provider="groq", model=GROQ_MODEL)


_CALLERS = {"anthropic": _call_anthropic, "gemini": _call_gemini, "groq": _call_groq}


async def generate(
    system_blocks: Sequence[str],
    messages: list[dict],
    *,
    max_tokens: int = 4000,
) -> LLMResult:
    """Try each configured provider in order; raise LLMUnavailable if none works."""
    providers = configured_providers()
    if not providers:
        raise LLMUnavailable("no LLM API key configured")
    errors = []
    for name in providers:
        try:
            return await _CALLERS[name](system_blocks, messages, max_tokens)
        except LLMUnavailable as exc:
            log.warning("LLM provider %s failed: %s", name, exc)
            errors.append(f"{name}: {exc}")
        except Exception as exc:  # network oddities should not take the feature down
            log.warning("LLM provider %s crashed: %s", name, exc)
            errors.append(f"{name}: {str(exc)[:120]}")
    raise LLMUnavailable("; ".join(errors))
