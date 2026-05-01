"""Extraction Agent — N-pass LLM extraction with Pydantic validation and self-correction.

Batches within each pass and all passes run concurrently, capped by a semaphore.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.db.client import get_db
from app.db.utils import run_aql
from app.extraction.prompts import get_template
from app.extraction.state import ExtractionPipelineState, StepLog, TokenUsage
from app.models.ontology import ExtractionResult

log = logging.getLogger(__name__)

_MAX_RETRIES_PER_BATCH = 5
_MAX_CONCURRENCY = 40


def _get_llm(model_name: str) -> Any:
    """Instantiate the LLM based on model name."""
    if "claude" in model_name.lower() or "anthropic" in model_name.lower():
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model_name,  # type: ignore[call-arg]
            api_key=settings.anthropic_api_key,  # type: ignore[arg-type]
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
            chunk_id = chunk.get("_key") or chunk.get("id") or chunk.get("chunk_id") or str(j)
            text_parts.append(f"[Chunk {j} | source_chunk_id={chunk_id}]\n{chunk.get('text', '')}")
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
        if "attributes" not in cls:
            cls["attributes"] = []
        if "relationships" not in cls:
            cls["relationships"] = []
        if "evidence" not in cls:
            cls["evidence"] = []
        if "parent_evidence" not in cls:
            cls["parent_evidence"] = []
        if "confidence" in cls:
            cls["confidence"] = max(0.0, min(1.0, float(cls["confidence"])))
        for prop in cls.get("properties", []):
            if "confidence" not in prop:
                prop["confidence"] = 0.5
            else:
                prop["confidence"] = max(0.0, min(1.0, float(prop["confidence"])))
            if "evidence" not in prop:
                prop["evidence"] = []
        for attr in cls.get("attributes", []):
            if "confidence" not in attr:
                attr["confidence"] = 0.5
            else:
                attr["confidence"] = max(0.0, min(1.0, float(attr["confidence"])))
            if "evidence" not in attr:
                attr["evidence"] = []
        for rel in cls.get("relationships", []):
            if "confidence" not in rel:
                rel["confidence"] = 0.5
            else:
                rel["confidence"] = max(0.0, min(1.0, float(rel["confidence"])))
            if "evidence" not in rel:
                rel["evidence"] = []

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
            run_aql(
                db,
                query,
                bind_vars={"doc_id": document_id, "embedding": sample_embedding},
            )
        )
        return result if result else chunks
    except Exception:
        log.debug("RAG chunk retrieval unavailable, using provided chunks")
        return chunks


async def _extract_batch(
    llm: Any,
    template: Any,
    batch_idx: int,
    batch_text: str,
    pass_num: int,
    model_name: str,
    domain_context: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    run_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[list[Any], list[str], dict[str, int]]:
    """Extract ontology classes from a single batch. Returns (classes, errors, token_counts)."""
    async with semaphore:
        relevant_chunks = _retrieve_relevant_chunks(document_id, chunks, batch_text)
        if relevant_chunks and relevant_chunks is not chunks:
            rag_text = "\n\n".join(c.get("text", "") for c in relevant_chunks[:5])
            batch_text = f"{batch_text}\n\n--- RELATED CONTEXT ---\n{rag_text}"

        extra_vars = {"pass_number": pass_num, "model_name": model_name}
        system_msg, user_msg = template.render(
            chunks_text=batch_text,
            domain_context=domain_context,
            extra_vars=extra_vars,
        )

        tokens = {"prompt_tokens": 0, "completion_tokens": 0}
        last_error: str | None = None
        result: ExtractionResult | None = None
        errors: list[str] = []

        for retry in range(_MAX_RETRIES_PER_BATCH):
            try:
                messages = [SystemMessage(content=system_msg), HumanMessage(content=user_msg)]
                if last_error and "Expecting value" not in last_error:
                    messages.append(
                        HumanMessage(
                            content=(
                                f"Your previous response failed validation: {last_error}\n"
                                "Please fix the JSON and try again."
                            )
                        )
                    )

                response = await llm.ainvoke(messages)
                raw_text = (
                    response.content if isinstance(response.content, str) else str(response.content)
                )

                if not raw_text or not raw_text.strip():
                    raise ValueError("LLM returned empty response")

                if hasattr(response, "usage_metadata") and response.usage_metadata:
                    usage = response.usage_metadata
                    tokens["prompt_tokens"] += usage.get("input_tokens", 0)
                    tokens["completion_tokens"] += usage.get("output_tokens", 0)

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
                if "empty response" in last_error.lower() or "Expecting value" in last_error:
                    await asyncio.sleep(2 * (retry + 1))
                if retry == _MAX_RETRIES_PER_BATCH - 1:
                    errors.append(
                        f"Pass {pass_num} batch {batch_idx}: "
                        f"failed after {_MAX_RETRIES_PER_BATCH} retries: {last_error}"
                    )

        classes = list(result.classes) if result else []
        return classes, errors, tokens


async def _run_single_pass(
    pass_num: int,
    llm: Any,
    template: Any,
    chunk_batches: list[str],
    model_name: str,
    domain_context: str,
    document_id: str,
    chunks: list[dict[str, Any]],
    run_id: str,
    semaphore: asyncio.Semaphore,
) -> tuple[ExtractionResult, list[str], dict[str, int]]:
    """Run one extraction pass with all batches concurrent."""
    log.info("extractor pass %d started (%d batches)", pass_num, len(chunk_batches))

    tasks = [
        _extract_batch(
            llm=llm,
            template=template,
            batch_idx=idx,
            batch_text=batch_text,
            pass_num=pass_num,
            model_name=model_name,
            domain_context=domain_context,
            document_id=document_id,
            chunks=chunks,
            run_id=run_id,
            semaphore=semaphore,
        )
        for idx, batch_text in enumerate(chunk_batches)
    ]

    results = await asyncio.gather(*tasks)

    all_classes = []
    all_errors = []
    pass_tokens = {"prompt_tokens": 0, "completion_tokens": 0}

    for classes, errors, tokens in results:
        all_classes.extend(classes)
        all_errors.extend(errors)
        pass_tokens["prompt_tokens"] += tokens["prompt_tokens"]
        pass_tokens["completion_tokens"] += tokens["completion_tokens"]

    pass_result = ExtractionResult(
        classes=all_classes,
        pass_number=pass_num,
        model=model_name,
        token_usage=(pass_tokens["prompt_tokens"] + pass_tokens["completion_tokens"]) or None,
    )

    log.info(
        "extractor pass %d completed: %d classes, %d errors",
        pass_num,
        len(all_classes),
        len(all_errors),
    )

    return pass_result, all_errors, pass_tokens


async def extractor_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node: run N-pass extraction concurrently with self-correction."""
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
    domain_context = state.get("domain_context", "")

    log.info(
        "extractor started",
        extra={
            "run_id": run_id,
            "model": model_name,
            "num_passes": num_passes,
            "chunk_count": len(chunks),
            "batch_size": batch_size,
        },
    )

    llm = _get_llm(model_name)
    template = get_template(template_key)
    total_tokens = TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    chunk_batches = _batch_chunks(chunks, batch_size)
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)

    # Run all passes concurrently — each pass runs its batches concurrently too
    pass_tasks = [
        _run_single_pass(
            pass_num=p,
            llm=llm,
            template=template,
            chunk_batches=chunk_batches,
            model_name=model_name,
            domain_context=domain_context,
            document_id=document_id,
            chunks=chunks,
            run_id=run_id,
            semaphore=semaphore,
        )
        for p in range(1, num_passes + 1)
    ]

    pass_outputs = await asyncio.gather(*pass_tasks)

    pass_results: list[ExtractionResult] = []
    for pass_result, pass_errors, pass_tokens in pass_outputs:
        pass_results.append(pass_result)
        errors.extend(pass_errors)
        total_tokens["prompt_tokens"] = (
            total_tokens.get("prompt_tokens", 0) + pass_tokens["prompt_tokens"]
        )
        total_tokens["completion_tokens"] = (
            total_tokens.get("completion_tokens", 0) + pass_tokens["completion_tokens"]
        )

    total_tokens["total_tokens"] = total_tokens.get("prompt_tokens", 0) + total_tokens.get(
        "completion_tokens", 0
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

    log.info(
        "extractor completed: %d passes, %d total classes, %.1fs",
        len(pass_results),
        sum(len(r.classes) for r in pass_results),
        duration,
    )

    return {
        "extraction_passes": pass_results,
        "errors": errors,
        "token_usage": total_tokens,
        "step_logs": [step_log],
    }
