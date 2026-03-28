"""Prompt template system for extraction pipeline.

Templates are keyed by name and support domain ontology context injection.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any

log = logging.getLogger(__name__)

_TEMPLATE_REGISTRY: dict[str, PromptTemplate] = {}


class PromptTemplate:
    """A reusable extraction prompt with placeholders for context injection."""

    def __init__(
        self,
        key: str,
        system_prompt: str,
        user_prompt: str,
        description: str = "",
    ) -> None:
        self.key = key
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.description = description

    def render(
        self,
        *,
        chunks_text: str,
        domain_context: str = "",
        extra_vars: dict[str, Any] | None = None,
    ) -> tuple[str, str]:
        """Return (system_message, user_message) with variables substituted."""
        variables = {
            "chunks_text": chunks_text,
            "domain_context": domain_context,
            **(extra_vars or {}),
        }
        system = self.system_prompt.format(**variables)
        user = self.user_prompt.format(**variables)
        return system, user


def register_template(template: PromptTemplate) -> None:
    """Register a prompt template for use in the extraction pipeline."""
    _TEMPLATE_REGISTRY[template.key] = template
    log.debug("registered prompt template", extra={"key": template.key})


def get_template(key: str) -> PromptTemplate:
    """Retrieve a registered prompt template by key.

    Raises KeyError if not found.
    """
    if not _TEMPLATE_REGISTRY:
        _load_builtin_templates()
    if key not in _TEMPLATE_REGISTRY:
        raise KeyError(f"Prompt template '{key}' not found. Available: {list(_TEMPLATE_REGISTRY)}")
    return _TEMPLATE_REGISTRY[key]


def list_templates() -> list[str]:
    """Return all registered template keys."""
    if not _TEMPLATE_REGISTRY:
        _load_builtin_templates()
    return list(_TEMPLATE_REGISTRY.keys())


def _load_builtin_templates() -> None:
    """Auto-import built-in template modules so they self-register."""
    for module_name in ("tier1_standard", "tier1_technical"):
        importlib.import_module(f"app.extraction.prompts.{module_name}")
