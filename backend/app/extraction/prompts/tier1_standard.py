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
- Identify owl:Class concepts with their hierarchical relationships (rdfs:subClassOf)
- Extract ATTRIBUTES and RELATIONSHIPS separately for each class:
  * "attributes" = owl:DatatypeProperty — scalar values like name, date, amount. \
    The range is always an XSD datatype (e.g., xsd:string, xsd:integer, xsd:date, \
    xsd:boolean, xsd:decimal, xsd:dateTime, xsd:float, xsd:anyURI)
  * "relationships" = owl:ObjectProperty — connections between classes. The \
    target_class_uri MUST be the URI of another class you are extracting in \
    this same response
- Use a SINGLE consistent URI namespace for ALL classes (e.g., http://example.org/domain#ClassName)
- Assign confidence scores: 1.0 for explicitly stated, lower for inferred
- Set parent_uri for subclass relationships; null for root/top-level classes
- NEVER set parent_uri to the class's own URI (a class cannot be a subclass of itself)
- Focus on domain-specific concepts, not generic terms
- Extract ALL inter-class relationships explicitly stated in the text. If the text \
  says "A Customer holds Accounts", extract: (1) both Customer and Account as \
  classes, AND (2) a relationship "holds" on Customer with target_class_uri \
  pointing to the Account class URI
- Do NOT create relationships pointing to classes you haven't extracted. If the \
  target class is not in your classes array, either extract it as a class or \
  model the value as an attribute with an appropriate XSD datatype instead"""

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
