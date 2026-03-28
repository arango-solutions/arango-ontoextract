"""Standard Tier 1 extraction prompt for general domain documents."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are an expert ontology engineer specializing in OWL 2, RDFS, and knowledge \
representation. Your task is to extract a formal domain ontology from the \
provided text.

{domain_context}

You MUST output valid JSON matching the following schema exactly:

{{
  "classes": [
    {{
      "uri": "string (namespace#ClassName)",
      "label": "string (human-readable name)",
      "description": "string (1-2 sentence description)",
      "parent_uri": "string | null (URI of parent class via rdfs:subClassOf)",
      "classification": "new | existing | extension",
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
- Identify owl:Class concepts with their hierarchical relationships (rdfs:subClassOf)
- Extract owl:ObjectProperty and owl:DatatypeProperty with domain/range
- Use consistent URI namespaces (e.g., http://example.org/domain#ClassName)
- Assign confidence scores: 1.0 for explicitly stated, lower for inferred
- Set parent_uri for subclass relationships; null for root classes
- Focus on domain-specific concepts, not generic terms"""

_USER = """\
Extract an OWL ontology from the following text chunks. Identify all domain \
classes, their hierarchical relationships, and properties.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions."""

_TEMPLATE = PromptTemplate(
    key="tier1_standard",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description="Standard extraction for general domain documents",
)

register_template(_TEMPLATE)
