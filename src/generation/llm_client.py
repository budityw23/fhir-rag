"""Provider-neutral async client for Claude, Gemini, Vertex AI, and Ollama."""

import logging
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# Gemini 2.5 counts internal reasoning against maxOutputTokens. At the previous
# 2048 cap, thinking consumed ~1750 tokens and answers were cut off mid-citation
# with finishReason=MAX_TOKENS. A bounded thinking budget plus more headroom
# keeps multi-hop reasoning available while guaranteeing room for the answer.
GOOGLE_MAX_OUTPUT_TOKENS = 4096
GOOGLE_THINKING_BUDGET = 512


def _google_generation_config() -> dict:
    """Generation config shared by the Gemini and Vertex request paths."""
    return {
        "maxOutputTokens": GOOGLE_MAX_OUTPUT_TOKENS,
        "thinkingConfig": {"thinkingBudget": GOOGLE_THINKING_BUDGET},
    }


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(
        self,
        provider: str,
        api_key: str | None = None,
        ollama_url: str | None = None,
        gemini_model: str = "gemini-2.5-flash",
    ):
        provider = provider.lower()
        if provider not in {"claude", "gemini", "vertex", "ollama"}:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        self.provider = provider
        self.api_key = api_key
        self.ollama_url = (ollama_url or "http://localhost:11434").rstrip("/")
        self.gemini_model = gemini_model

    async def generate(self, system_prompt: str, user_message: str) -> LLMResponse:
        """Send prompt to LLM and return response."""
        if self.provider == "claude":
            return await self._generate_claude(system_prompt, user_message)
        if self.provider == "gemini":
            return await self._generate_gemini(system_prompt, user_message)
        if self.provider == "vertex":
            return await self._generate_vertex(system_prompt, user_message)
        return await self._generate_ollama(system_prompt, user_message)

    async def _generate_claude(self, system_prompt: str, user_message: str) -> LLMResponse:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=self.api_key)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        )
        content = "".join(
            block.text for block in response.content if getattr(block, "type", "text") == "text"
        )
        usage = response.usage
        return LLMResponse(
            content=content,
            model=response.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    async def _generate_gemini(self, system_prompt: str, user_message: str) -> LLMResponse:
        """Generate a response through the Gemini Developer API."""
        return await self._generate_google(system_prompt, user_message, "gemini")

    async def _generate_vertex(self, system_prompt: str, user_message: str) -> LLMResponse:
        """Generate a response through Vertex AI Express Mode."""
        return await self._generate_google(system_prompt, user_message, "vertex")

    async def _generate_google(
        self, system_prompt: str, user_message: str, provider: str
    ) -> LLMResponse:
        if not self.api_key:
            raise ValueError(f"API key must be set when LLM_PROVIDER={provider}")

        if provider == "vertex":
            # Vertex AI Express Mode accepts only user and model message roles.
            payload = {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": f"{system_prompt}\n\n{user_message}"}],
                    }
                ],
                "generationConfig": _google_generation_config(),
            }
            url = (
                "https://aiplatform.googleapis.com/v1/publishers/google/models/"
                f"{self.gemini_model}:generateContent"
            )
        else:
            payload = {
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_message}]}],
                "generationConfig": _google_generation_config(),
            }
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self.gemini_model}:generateContent"
            )
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers={"x-goog-api-key": self.api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        candidates = data.get("candidates", [])
        parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
        content = "".join(part.get("text", "") for part in parts)
        usage = data.get("usageMetadata", {})
        if candidates and candidates[0].get("finishReason") == "MAX_TOKENS":
            # Otherwise the answer is returned cut off mid-sentence and the
            # citation mapper reports it as ungrounded for the wrong reason.
            logger.warning(
                "%s response hit maxOutputTokens (thinking=%s, output=%s); answer truncated",
                provider,
                usage.get("thoughtsTokenCount", 0),
                usage.get("candidatesTokenCount", 0),
            )
        return LLMResponse(
            content=content,
            model=data.get("modelVersion", self.gemini_model),
            input_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
        )

    async def _generate_ollama(self, system_prompt: str, user_message: str) -> LLMResponse:
        payload = {
            "model": "llama3.2",
            "prompt": f"{system_prompt}\n\n{user_message}",
            "stream": False,
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{self.ollama_url}/api/generate", json=payload)
            response.raise_for_status()
            data = response.json()
        return LLMResponse(
            content=data.get("response", ""),
            model=data.get("model", payload["model"]),
            input_tokens=int(data.get("prompt_eval_count", 0) or 0),
            output_tokens=int(data.get("eval_count", 0) or 0),
        )
