"""Extraction Agent — N-pass LLM extraction with Pydantic validation and self-correction."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.extraction.prompts import get_template
from app.extraction.state import ExtractionPipelineState, StepLog, TokenUsage
from app.models.ontology import ExtractionResult

log = logging.getLogger(__name__)

_MAX_RETRIES_PER_PASS = 3


def _get_llm(model_name: str) -> Any:
    """Instantiate the LLM based on model name."""
    if "claude" in model_name.lower() or "anthropic" in model_name.lower():
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,
            api_key=settings.anthropic_api_key,
            max_tokens=4096,
        )
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model_name,
        "api_key": settings.openai_api_key,
        "max_tokens": 4096,
    }
    if settings.openai_base_url:
        kwargs["base_url"] = settings.openai_base_url
    return ChatOpenAI(**kwargs)


def _batch_chunks(chunks: list[dict[str, Any]], batch_size: int) -> list[str]:
    """Combine chunks into batched text blocks for prompt injection."""
    batches: list[str] = []
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        text_parts = []
        for j, chunk in enumerate(batch, start=i + 1):
            text_parts.append(f"[Chunk {j}]\n{chunk.get('text', '')}")
        batches.append("\n\n".join(text_parts))
    return batches


def _parse_llm_response(raw_text: str, pass_number: int, model_name: str) -> ExtractionResult:
    """Parse LLM response text into ExtractionResult.

    Strips markdown fences and validates against Pydantic.
    """
    text = raw_text.strip()
    if text.startswith("```"):
        first_newline = text.index("\n")
        last_fence = text.rfind("```")
        text = text[first_newline + 1 : last_fence].strip()

    data = json.loads(text)

    if "pass_number" not in data:
        data["pass_number"] = pass_number
    if "model" not in data:
        data["model"] = model_name

    for cls in data.get("classes", []):
        if "properties" not in cls:
            cls["properties"] = []
        for prop in cls.get("properties", []):
            if "confidence" not in prop:
                prop["confidence"] = 0.5

    return ExtractionResult.model_validate(data)


def _retrieve_relevant_chunks(
    document_id: str,
    chunks: list[dict[str, Any]],
    batch_text: str,
) -> list[dict[str, Any]]:
    """RAG: retrieve relevant chunks via vector similarity.

    Falls back to returning the input chunks if vector search is unavailable.
    """
    try:
        from app.db.client import get_db

        db = get_db()
        if not db.has_collection("chunks"):
            return chunks

        sample_embedding = chunks[0].get("embedding") if chunks else None
        if not sample_embedding:
            return chunks

        query = """\
FOR chunk IN chunks
  FILTER chunk.doc_id == @doc_id
  LET sim = COSINE_SIMILARITY(chunk.embedding, @embedding)
  FILTER sim > 0.7
  SORT sim DESC
  LIMIT 10
  RETURN chunk"""
        result = list(
            db.aql.execute(
                query,
                bind_vars={"doc_id": document_id, "embedding": sample_embedding},
            )
        )
        return result if result else chunks
    except Exception:
        log.debug("RAG chunk retrieval unavailable, using provided chunks")
        return chunks


def extractor_node(state: ExtractionPipelineState) -> dict:
    """LangGraph node: run N-pass extraction with self-correction."""
    start = time.time()
    run_id = state.get("run_id", "unknown")
    document_id = state.get("document_id", "")
    chunks = state.get("document_chunks", [])
    config = state.get("strategy_config", {})
    errors = list(state.get("errors", []))

    model_name = config.get("model_name", settings.llm_extraction_model)
    template_key = config.get("prompt_template_key", "tier1_standard")
    batch_size = config.get("chunk_batch_size", 5)
    num_passes = config.get("num_passes", settings.extraction_passes)

    log.info(
        "extractor started",
        extra={
            "run_id": run_id,
            "model": model_name,
            "num_passes": num_passes,
            "chunk_count": len(chunks),
        },
    )

    llm = _get_llm(model_name)
    template = get_template(template_key)
    pass_results: list[ExtractionResult] = []
    total_tokens = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    chunk_batches = _batch_chunks(chunks, batch_size)

    for pass_num in range(1, num_passes + 1):
        log.info("extractor pass started", extra={"run_id": run_id, "pass": pass_num})
        all_classes = []
        pass_token_total = 0

        for batch_idx, batch_text in enumerate(chunk_batches):
            relevant_chunks = _retrieve_relevant_chunks(document_id, chunks, batch_text)
            if relevant_chunks and relevant_chunks is not chunks:
                rag_text = "\n\n".join(c.get("text", "") for c in relevant_chunks[:5])
                batch_text = f"{batch_text}\n\n--- RELATED CONTEXT ---\n{rag_text}"

            extra_vars = {"pass_number": pass_num, "model_name": model_name}
            system_msg, user_msg = template.render(
                chunks_text=batch_text,
                extra_vars=extra_vars,
            )

            last_error: str | None = None
            result: ExtractionResult | None = None

            for retry in range(_MAX_RETRIES_PER_PASS):
                try:
                    messages = [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]
                    if last_error:
                        messages.append(
                            HumanMessage(
                                content=(
                                    f"Your previous response failed validation: {last_error}\n"
                                    "Please fix the JSON and try again."
                                )
                            )
                        )

                    response = llm.invoke(messages)
                    raw_text = (
                        response.content
                        if isinstance(response.content, str)
                        else str(response.content)
                    )

                    if hasattr(response, "usage_metadata") and response.usage_metadata:
                        usage = response.usage_metadata
                        pass_token_total += getattr(usage, "total_tokens", 0)
                        total_tokens["prompt_tokens"] = total_tokens.get(
                            "prompt_tokens", 0
                        ) + getattr(usage, "input_tokens", 0)
                        total_tokens["completion_tokens"] = total_tokens.get(
                            "completion_tokens", 0
                        ) + getattr(usage, "output_tokens", 0)

                    result = _parse_llm_response(raw_text, pass_num, model_name)
                    break

                except Exception as exc:
                    last_error = str(exc)
                    log.warning(
                        "extractor parse error, retrying",
                        extra={
                            "run_id": run_id,
                            "pass": pass_num,
                            "batch": batch_idx,
                            "retry": retry + 1,
                            "error": last_error,
                        },
                    )
                    if retry == _MAX_RETRIES_PER_PASS - 1:
                        errors.append(
                            f"Pass {pass_num} batch {batch_idx}: "
                            f"failed after {_MAX_RETRIES_PER_PASS} retries: {last_error}"
                        )

            if result:
                all_classes.extend(result.classes)

        total_tokens["total_tokens"] = (
            total_tokens.get("prompt_tokens", 0) + total_tokens.get("completion_tokens", 0)
        )

        pass_result = ExtractionResult(
            classes=all_classes,
            pass_number=pass_num,
            model=model_name,
            token_usage=pass_token_total or None,
        )
        pass_results.append(pass_result)
        log.info(
            "extractor pass completed",
            extra={
                "run_id": run_id,
                "pass": pass_num,
                "classes_found": len(all_classes),
                "tokens": pass_token_total,
            },
        )

    duration = time.time() - start
    step_log = StepLog(
        step="extractor",
        status="completed" if pass_results else "failed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        tokens=total_tokens,
        error=errors[-1] if errors else None,
        metadata={
            "num_passes": len(pass_results),
            "total_classes": sum(len(r.classes) for r in pass_results),
        },
    )

    existing_logs = list(state.get("step_logs", []))
    existing_logs.append(step_log)

    return {
        "extraction_passes": pass_results,
        "current_step": "extractor",
        "errors": errors,
        "token_usage": total_tokens,
        "step_logs": existing_logs,
    }
