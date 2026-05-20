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
      "parent_evidence": [
        {{
          "source_chunk_ids": ["string"],
          "source_spans": ["string"],
          "evidence_text": "string",
          "evidence_confidence": 0.0-1.0,
          "extraction_rationale": "string"
        }}
      ],
      "classification": "new | existing | extension",
      "confidence": 0.0-1.0,
      "evidence": [
        {{
          "source_chunk_ids": ["string"],
          "source_spans": ["string"],
          "evidence_text": "string",
          "evidence_confidence": 0.0-1.0,
          "extraction_rationale": "string"
        }}
      ],
      "attributes": [
        {{
          "uri": "string (namespace#attributeName)",
          "label": "string",
          "description": "string",
          "range_datatype": "string (XSD datatype, e.g., xsd:string or xsd:date)",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
        }}
      ],
      "relationships": [
        {{
          "uri": "string (namespace#relationshipName)",
          "label": "string (verb phrase, e.g., 'holds', 'contains', 'is managed by')",
          "description": "string",
          "target_class_uri": "string (MUST be the URI of another class in this response)",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
        }}
      ],
      "constraints": [
        {{
          "restriction_type": "minCardinality | maxCardinality | cardinality | \
allValuesFrom | someValuesFrom | hasValue",
          "property_uri": "string (MUST match the URI of an attribute or \
relationship of THIS class)",
          "restriction_value": "int for cardinality kinds | URI string for \
allValuesFrom/someValuesFrom | literal for hasValue",
          "description": "string (curator-readable rationale: e.g., 'each \
Account must have exactly one holder')",
          "confidence": 0.0-1.0,
          "evidence": [
            {{
              "source_chunk_ids": ["string"],
              "source_spans": ["string"],
              "evidence_text": "string",
              "evidence_confidence": 0.0-1.0,
              "extraction_rationale": "string"
            }}
          ]
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
- Cite source evidence for every class, parent_uri, attribute, and relationship. \
  Use the `source_chunk_id` values shown in chunk headers. Keep `evidence_text` \
  to the shortest supporting quote from the text.
- Set parent_uri for subclass relationships; null for root/top-level classes
- NEVER set parent_uri to the class's own URI (a class cannot be a subclass of itself)
- Focus on domain-specific concepts, not generic terms
- Extract ALL inter-class relationships explicitly stated in the text. If the text \
  says "A Customer holds Accounts", extract: (1) both Customer and Account as \
  classes, AND (2) a relationship "holds" on Customer with target_class_uri \
  pointing to the Account class URI
- Do NOT create relationships pointing to classes you haven't extracted. If the \
  target class is not in your classes array, either extract it as a class or \
  model the value as an attribute with an appropriate XSD datatype instead
- Extract OWL RESTRICTIONS as "constraints" on the class when the text states a \
  cardinality bound or a value restriction on one of the class's own attributes \
  or relationships. Examples:
  * "Each Account must have exactly one holder" → constraint with \
    restriction_type="cardinality", property_uri pointing to the "holder" \
    relationship, restriction_value=1
  * "Customers may have multiple accounts" → no cardinality constraint (lower \
    bound is 0, upper bound is unbounded — default OWL semantics already say this)
  * "Every Account has at least one signatory and at most five" → TWO \
    constraints on the same property: one minCardinality=1 and one \
    maxCardinality=5
  * "The status of an Account is always one of: Open, Frozen, Closed" → \
    constraint with restriction_type="hasValue" is NOT the right encoding \
    (hasValue is for a single value); model this as an attribute with an \
    enumerated range instead, and only emit a constraint if a single explicit \
    value is asserted
  * Only emit a constraint when the text explicitly states a bound or value; \
    do NOT infer "exactly one" from a singular noun unless the text says so. \
    property_uri MUST match a uri inside this class's "attributes" or \
    "relationships" — never reference a property from a different class."""

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
