"""Run the diabetes validation questions through the complete RAG pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.config import settings
from src.database import close_pool, init_pool
from src.generation.citation_mapper import CITATION_PATTERN, map_citations
from src.generation.llm_client import LLMClient
from src.ingestion.embedder import Embedder
from src.retrieval.context_builder import build_context
from src.retrieval.hybrid_search import hybrid_search
from src.retrieval.reference_resolver import resolve_references

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS_PATH = ROOT / "eval" / "questions.json"
RESULTS_DIR = ROOT / "eval" / "results"
PROMPT_ENVIRONMENT = Environment(
    loader=FileSystemLoader(ROOT / "src" / "generation" / "prompts"),
    undefined=StrictUndefined,
)


@dataclass
class EvalResult:
    question: str
    retrieval_recall: float
    citation_accuracy: float
    answer_contains: float
    confidence: str
    latency_ms: int


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict[str, Any]]:
    """Load and validate the evaluation question list."""
    questions = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(questions, list) or len(questions) != 50:
        raise ValueError("Evaluation dataset must contain exactly 50 questions")
    required = {
        "id", "question", "patient_ref", "expected_resource_types", "expected_codes",
        "expected_answer_contains", "category", "diabetes_type",
    }
    for question in questions:
        missing = required - question.keys()
        if missing:
            raise ValueError(f"{question.get('id', 'unknown')} is missing {sorted(missing)}")
    return questions


def _matches_expectation(answer: str, expectation: str) -> bool:
    """Match literal phrases plus the compact alternatives used in questions.json."""
    answer_lower = answer.lower()
    alternatives = [part.strip() for part in expectation.split("|") if part.strip()]
    if any(part.lower() in answer_lower for part in alternatives):
        return True
    if expectation == "date" or expectation.endswith("date"):
        return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", answer))
    if expectation in {"numeric value", "percentage value", "dosage value", "numeric count"}:
        return bool(re.search(r"\b\d+(?:\.\d+)?\s*%?|\b\d+\b", answer))
    if expectation in {"medication names", "medication name", "description", "clinical correlation"}:
        return expectation.split()[0].lower() in answer_lower
    if expectation in {"multiple date-value pairs", "chronological events with dates"}:
        return len(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", answer)) >= 2
    if expectation == "duration or date":
        return bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b|\b\d+\s+(?:year|month|day)s?\b", answer_lower))
    if expectation == "type if applicable":
        return any(word in answer_lower for word in ("glargine", "lispro", "type", "basal", "bolus"))
    if expectation == "listing of screenings":
        return any(word in answer_lower for word in ("eye", "foot", "kidney", "lipid"))
    return False


def _retrieval_recall(question: dict[str, Any], resources: list[Any]) -> float:
    expected = set(question["expected_resource_types"])
    if not expected:
        return 1.0 if not resources else 0.0
    found = {resource.resource_type for resource in resources}
    return len(expected & found) / len(expected)


def _citation_accuracy(response: str, resources: list[Any]) -> float:
    matches = CITATION_PATTERN.findall(response)
    if not matches:
        return 0.0
    available = {
        (resource.resource_type.lower(), resource.resource_id.split("/", 1)[-1].lower())
        for resource in resources
    }
    valid = sum((resource_type.lower(), resource_id.lower()) in available for resource_type, resource_id in matches)
    return valid / len(matches)


async def evaluate_question(
    question: dict[str, Any],
    pool,
    embedder: Embedder,
    llm_client: LLMClient,
) -> EvalResult:
    """Run one question through embedding, retrieval, resolution, generation, and mapping."""
    started = time.perf_counter()
    query = question["question"]
    embedding = embedder.embed_query(query)
    # The dataset deliberately uses an unresolved placeholder patient reference.
    primary = await hybrid_search(pool, embedding, top_k=settings.top_k)
    supplementary = await resolve_references(pool, primary, max_hops=settings.max_reference_hops)
    resources = primary + supplementary
    context = build_context(primary, supplementary)
    prompt = PROMPT_ENVIRONMENT.get_template("clinical_qa.jinja2").render(
        context=context,
        question=query,
    )
    llm_response = await llm_client.generate(prompt, query)
    grounded = map_citations(llm_response.content, query, resources)
    expected = question["expected_answer_contains"]
    answer_contains = sum(
        _matches_expectation(grounded.answer, expectation) for expectation in expected
    ) / len(expected) if expected else 1.0
    return EvalResult(
        question=query,
        retrieval_recall=_retrieval_recall(question, primary),
        citation_accuracy=_citation_accuracy(llm_response.content, resources),
        answer_contains=answer_contains,
        confidence=grounded.confidence,
        latency_ms=round((time.perf_counter() - started) * 1000),
    )


def _aggregate(results: list[EvalResult]) -> dict[str, Any]:
    if not results:
        return {"question_count": 0}
    return {
        "question_count": len(results),
        "retrieval_recall": sum(r.retrieval_recall for r in results) / len(results),
        "citation_accuracy": sum(r.citation_accuracy for r in results) / len(results),
        "answer_contains": sum(r.answer_contains for r in results) / len(results),
        "confidence_counts": {
            level: sum(result.confidence == level for result in results)
            for level in ("grounded", "partially_grounded", "ungrounded")
        },
        "latency_ms": {
            "mean": round(sum(r.latency_ms for r in results) / len(results)),
            "max": max(r.latency_ms for r in results),
        },
    }


def write_results(results: list[EvalResult], output_path: Path | None = None) -> Path:
    """Write per-question results and aggregate metrics to a JSON report."""
    output_path = output_path or RESULTS_DIR / "evaluation_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "results": [asdict(result) for result in results],
        "summary": _aggregate(results),
    }
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output_path


def print_results(results: list[EvalResult]) -> None:
    """Print a compact per-question table and aggregate summary."""
    headers = ("Question", "Recall", "Citations", "Contains", "Confidence", "Latency")
    print(" | ".join(headers))
    print("-" * 92)
    for index, result in enumerate(results, 1):
        print(
            f"{index:02d} | {result.retrieval_recall:.2f} | {result.citation_accuracy:.2f} | "
            f"{result.answer_contains:.2f} | {result.confidence:<18} | {result.latency_ms} ms"
        )
    print(json.dumps(_aggregate(results), indent=2))


async def run_evaluation(
    questions: list[dict[str, Any]] | None = None,
    output_path: Path | None = None,
) -> list[EvalResult]:
    """Run all evaluation questions using the configured database and LLM provider."""
    questions = questions or load_questions()
    pool = await init_pool()
    embedder = Embedder(settings.embedding_model)
    llm_client = LLMClient(
        settings.llm_provider,
        api_key=settings.anthropic_api_key,
        ollama_url=settings.ollama_base_url,
    )
    try:
        results = []
        for index, question in enumerate(questions, 1):
            print(f"Evaluating {index}/{len(questions)}: {question['id']}")
            results.append(await evaluate_question(question, pool, embedder, llm_client))
        print_results(results)
        path = write_results(results, output_path)
        print(f"JSON results: {path}")
        return results
    finally:
        await close_pool()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=QUESTIONS_PATH)
    parser.add_argument("--output", type=Path, default=RESULTS_DIR / "evaluation_results.json")
    args = parser.parse_args()
    asyncio.run(run_evaluation(load_questions(args.questions), args.output))


if __name__ == "__main__":
    main()
