from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.generation.llm_client import LLMClient


@pytest.mark.asyncio
async def test_claude_provider_returns_content_and_usage():
    response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="The HbA1c was 7.2%.")],
        model="claude-sonnet-4-6",
        usage=SimpleNamespace(input_tokens=42, output_tokens=11),
    )
    messages = Mock()
    messages.create = AsyncMock(return_value=response)
    client_instance = SimpleNamespace(messages=messages)

    with patch("anthropic.AsyncAnthropic", return_value=client_instance) as constructor:
        result = await LLMClient("claude", api_key="test-key").generate("system", "question")

    constructor.assert_called_once_with(api_key="test-key")
    messages.create.assert_awaited_once_with(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system="system",
        messages=[{"role": "user", "content": "question"}],
    )
    assert result.content == "The HbA1c was 7.2%."
    assert result.model == "claude-sonnet-4-6"
    assert result.input_tokens == 42
    assert result.output_tokens == 11


@pytest.mark.asyncio
async def test_ollama_provider_calls_generate_endpoint_and_returns_usage():
    response = Mock()
    response.json.return_value = {
        "model": "llama3.2",
        "response": "Metformin is active [MedicationRequest/med-1].",
        "prompt_eval_count": 19,
        "eval_count": 8,
    }
    response.raise_for_status = Mock()
    http_client = Mock()
    http_client.post = AsyncMock(return_value=response)
    http_context = Mock()
    http_context.__aenter__ = AsyncMock(return_value=http_client)
    http_context.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=http_context) as constructor:
        result = await LLMClient("ollama", ollama_url="http://ollama:11434").generate(
            "system", "question"
        )

    constructor.assert_called_once_with(timeout=120.0)
    http_client.post.assert_awaited_once_with(
        "http://ollama:11434/api/generate",
        json={"model": "llama3.2", "prompt": "system\n\nquestion", "stream": False},
    )
    assert result.content.startswith("Metformin")
    assert result.input_tokens == 19
    assert result.output_tokens == 8


@pytest.mark.asyncio
async def test_gemini_provider_calls_generate_content_and_returns_usage():
    response = Mock()
    response.json.return_value = {
        "modelVersion": "gemini-2.5-flash",
        "candidates": [{"content": {"parts": [{"text": "Gemini response."}]}}],
        "usageMetadata": {"promptTokenCount": 21, "candidatesTokenCount": 7},
    }
    response.raise_for_status = Mock()
    http_client = Mock()
    http_client.post = AsyncMock(return_value=response)
    http_context = Mock()
    http_context.__aenter__ = AsyncMock(return_value=http_client)
    http_context.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=http_context) as constructor:
        result = await LLMClient("gemini", api_key="test-key").generate("system", "question")

    constructor.assert_called_once_with(timeout=120.0)
    http_client.post.assert_awaited_once_with(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-2.5-flash:generateContent",
        headers={"x-goog-api-key": "test-key"},
        json={
            "systemInstruction": {"parts": [{"text": "system"}]},
            "contents": [{"role": "user", "parts": [{"text": "question"}]}],
            "generationConfig": {
        "maxOutputTokens": 4096,
        # Gemini 2.5 charges internal reasoning to maxOutputTokens; an
        # unbounded budget truncated answers mid-citation.
        "thinkingConfig": {"thinkingBudget": 512},
    },
        },
    )
    assert result.content == "Gemini response."
    assert result.model == "gemini-2.5-flash"
    assert result.input_tokens == 21
    assert result.output_tokens == 7


@pytest.mark.asyncio
async def test_vertex_provider_calls_express_mode_endpoint():
    response = Mock()
    response.json.return_value = {"candidates": [{"content": {"parts": [{"text": "OK"}]}}]}
    response.raise_for_status = Mock()
    http_client = Mock()
    http_client.post = AsyncMock(return_value=response)
    http_context = Mock()
    http_context.__aenter__ = AsyncMock(return_value=http_client)
    http_context.__aexit__ = AsyncMock(return_value=False)

    with patch("httpx.AsyncClient", return_value=http_context):
        result = await LLMClient("vertex", api_key="test-key").generate("system", "question")

    http_client.post.assert_awaited_once_with(
        "https://aiplatform.googleapis.com/v1/publishers/google/models/"
        "gemini-2.5-flash:generateContent",
        headers={"x-goog-api-key": "test-key"},
        json={
            "contents": [{"role": "user", "parts": [{"text": "system\n\nquestion"}]}],
            "generationConfig": {
        "maxOutputTokens": 4096,
        # Gemini 2.5 charges internal reasoning to maxOutputTokens; an
        # unbounded budget truncated answers mid-citation.
        "thinkingConfig": {"thinkingBudget": 512},
    },
        },
    )
    assert result.content == "OK"


def test_client_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        LLMClient("local")
