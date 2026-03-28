"""Technical document prompt variant — emphasises taxonomic structure and standards."""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are an expert ontology engineer specializing in OWL 2, RDFS, and formal \
taxonomy construction from technical standards documents (ISO, W3C, NIST, \
RFC, etc.).

{domain_context}

You MUST output valid JSON matching the following schema exactly:

{{
  "classes": [
    {{
      "uri": "string (namespace#ClassName)",
      "label": "string (human-readable name)",
      "description": "string (precise technical definition)",
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
- Prioritize deep taxonomic hierarchies (rdfs:subClassOf chains)
- Extract precise technical definitions, not general descriptions
- Use the document's own terminology for labels
- Identify constraints and cardinality where stated
- Differentiate between object properties (links to classes) and datatype \
properties (links to XSD types)
- Assign higher confidence to concepts explicitly defined in the document
- For standards documents, preserve section/clause references in descriptions"""

_USER = """\
Extract a formal OWL taxonomy from the following technical document chunks. \
Focus on building a deep, precise class hierarchy with well-typed properties.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions."""

_TEMPLATE = PromptTemplate(
    key="tier1_technical",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description="Technical document variant with emphasis on taxonomic structure",
)

register_template(_TEMPLATE)
