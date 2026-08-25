"""Provider-neutral async client for Claude and Ollama."""

from dataclasses import dataclass

import httpx


@dataclass
class LLMResponse:
    content: str
    model: str
    input_tokens: int
    output_tokens: int


class LLMClient:
    def __init__(self, provider: str, api_key: str | None = None, ollama_url: str | None = None):
        provider = provider.lower()
        if provider not in {"claude", "ollama"}:
            raise ValueError(f"Unsupported LLM provider: {provider}")
        self.provider = provider
        self.api_key = api_key
        self.ollama_url = (ollama_url or "http://localhost:11434").rstrip("/")

    async def generate(self, system_prompt: str, user_message: str) -> LLMResponse:
        """Send prompt to LLM and return response."""
        if self.provider == "claude":
            return await self._generate_claude(system_prompt, user_message)
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

