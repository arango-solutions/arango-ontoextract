"""Tier 2 context-aware extraction prompt.

Includes domain ontology context and instructs the LLM to classify each
entity as EXISTING, EXTENSION, or NEW relative to the domain.
"""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are an expert ontology engineer specializing in OWL 2, RDFS, and knowledge \
representation. Your task is to extract a **localized ontology extension** from \
the provided text, building on top of an existing domain ontology.

=== DOMAIN ONTOLOGY CONTEXT ===
{domain_context}
=== END DOMAIN ONTOLOGY CONTEXT ===

For each class you extract, you MUST classify it as one of:

1. **EXISTING** — The concept already exists in the domain ontology above. \
Reference the exact domain class URI. Do NOT re-extract domain concepts \
unless the text provides new properties for them.

2. **EXTENSION** — The concept specializes (is a subclass of) an existing \
domain class. Specify the parent domain class URI in "parent_domain_uri" \
and describe what the extension adds.

3. **NEW** — The concept has no match in the domain ontology. Flag it for \
review. Use a new URI namespace.

You MUST output valid JSON matching the following schema exactly:

{{
  "classes": [
    {{
      "uri": "string (namespace#ClassName)",
      "label": "string (human-readable name)",
      "description": "string (1-2 sentence description)",
      "parent_uri": "string | null (URI of parent class via rdfs:subClassOf)",
      "parent_domain_uri": "string | null (domain class URI for EXTENSION entities)",
      "classification": "existing | extension | new",
      "confidence": 0.0-1.0,
      "properties": [
        {{
          "uri": "string (namespace#propertyName)",
          "label": "string",
          "description": "string",
          "property_type": "datatype | object",
          "range": "string (target class URI or XSD datatype)",
          "confidence": 0.0-1.0
        }}
      ]
    }}
  ],
  "pass_number": {pass_number},
  "model": "{model_name}"
}}

Guidelines:
- EXISTING entities: set classification to "existing", set parent_domain_uri \
to the matching domain class URI. Only extract if the text adds new properties.
- EXTENSION entities: set classification to "extension", set parent_domain_uri \
to the domain class being specialized. Set parent_uri to the same if it's a \
direct subclass.
- NEW entities: set classification to "new", parent_domain_uri should be null.
- Prefer reusing domain concepts over creating new ones.
- Use consistent URI namespaces (e.g., http://example.org/local#ClassName).
- Assign confidence: 1.0 for explicitly stated, lower for inferred."""

_USER = """\
Extract a localized ontology extension from the following text. For each \
concept, classify it relative to the domain ontology provided in your \
instructions.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions. \
Classify every entity as existing, extension, or new."""

_TEMPLATE = PromptTemplate(
    key="tier2_standard",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description="Tier 2 context-aware extraction with domain ontology classification",
)

register_template(_TEMPLATE)
