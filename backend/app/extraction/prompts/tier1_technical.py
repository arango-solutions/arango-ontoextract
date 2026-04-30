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
      "attributes": [
        {{
          "uri": "string (namespace#attributeName)",
          "label": "string",
          "description": "string",
          "range_datatype": "string (XSD type, e.g. xsd:string, xsd:integer, xsd:dateTime)",
          "confidence": 0.0-1.0
        }}
      ],
      "relationships": [
        {{
          "uri": "string (namespace#relationshipName)",
          "label": "string (verb phrase, e.g., 'holds', 'contains', 'is managed by')",
          "description": "string",
          "target_class_uri": "string (MUST be the URI of another class in this response)",
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
- Extract ATTRIBUTES and RELATIONSHIPS separately for each class:
  * "attributes" = owl:DatatypeProperty — scalar values (XSD types). Use for \
    quantities, identifiers, dates, names, and other literal values
  * "relationships" = owl:ObjectProperty — connections between classes. The \
    target_class_uri MUST be the URI of another class in this response
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
