"""Visual-aware Tier 1 extraction prompt (Stream 13 IMG.6).

Used when the strategy selector classifies a document as
``visual_heavy_presentation`` -- typically a PPTX deck or scanned PDF
where hierarchy and object-property evidence lives in slide titles,
visual placeholders, or alt-text rather than running prose.

The schema and JSON contract match ``tier1_standard`` so consistency
checking, validation, and downstream persistence work unchanged. The
*system* prompt is extended with explicit guidance on how to interpret
``[Slide N: Title]``, ``[Visual omitted: ...]``, ``[Visual (alt text):
...]`` and ``[Scanned ... page N: ...]`` markers, and to cite the
specific chunk-id those markers came from in ``parent_evidence`` so
curators can audit visual-derived hierarchy.
"""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are an expert ontology engineer specializing in OWL 2, RDFS, and knowledge \
representation. Your task is to extract a formal domain ontology from the \
provided text, which has been parsed from a *visual-heavy* document \
(typically a presentation deck or scanned report).

The text uses the same JSON schema and conventions as the standard Tier 1 \
prompt -- the deltas are entirely about how to read the chunked text.

{domain_context}

Visual markers in the chunked text:

- ``[Slide N: Title]`` and ``[Page N: Title]`` at the start of a chunk \
  introduce a slide or page boundary; ``Title`` is the slide/page title \
  placeholder and is usually a strong hierarchy hint (e.g., the title of \
  a section slide is often the parent class for everything that follows).
- ``[Visual omitted: slide N image M]`` or ``[Visual omitted: page N \
  image M]`` mark images / charts / diagrams whose pixels were NOT \
  captioned. Treat these as evidence that *something* visual exists on \
  that slide/page but do NOT invent its content -- you may only cite \
  this marker as evidence for a hierarchy relation when the same slide's \
  title or body text independently supports it.
- ``[Visual (alt text): ...]`` carries the author-provided alt text for \
  an image / chart. Alt text IS reliable evidence and may be cited as \
  ``parent_evidence`` for a subclass relation or as ``evidence`` for an \
  attribute / relationship.
- ``[Visual (caption): ...]`` carries an OCR- or vision-model-generated \
  caption for an image / chart. Captions are also reliable evidence and \
  may be cited as ``parent_evidence`` or ``evidence``. When the only \
  available evidence for a class is a caption, set ``evidence_confidence`` \
  no higher than 0.7 (the caption is a derived artifact).
- ``[Scanned or image-only page N: OCR not configured]`` means the page \
  has no extractable text. Do NOT invent content for those pages. If the \
  ontology is missing hierarchy that obviously belongs to a scanned \
  page, leave ``parent_uri`` ``null`` and rely on belief revision to \
  repair it later.

Output the same JSON schema as the standard Tier 1 prompt:

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
          "label": "string (verb phrase)",
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
      "constraints": []
    }}
  ],
  "pass_number": {pass_number},
  "model": "{model_name}"
}}

Visual-extraction guidelines (in addition to the standard tier-1 rules):

- Treat slide titles as PRIMARY hierarchy evidence. If slide 7 has title \
  "Mental Health Benefits" and the following slides cover specific \
  benefit programs, those programs are subclasses of MentalHealthBenefit \
  with ``parent_evidence`` citing the slide-7 title chunk-id.
- A title-only slide (no body text, no captioned visuals) STILL implies \
  the class exists. Emit the class with ``parent_uri`` matching the \
  surrounding section's class when the deck structure makes that obvious; \
  otherwise leave ``parent_uri`` ``null`` and confidence ~0.5.
- Cite source evidence for every class, parent_uri, attribute, and \
  relationship using the ``source_chunk_id`` values shown in chunk headers.
- For object-property evidence, prefer slide titles + body text over \
  pixel-less visual markers. When the only evidence is alt text, set \
  ``evidence_confidence`` no higher than 0.7.
- NEVER fabricate body text for a ``[Visual omitted: ...]`` or scanned \
  page. If the chunk text is only visual markers, you may still emit a \
  class (using the slide title) but you MUST NOT pretend to have read \
  diagram contents.
- Set ``parent_uri`` for subclass relationships; ``null`` for root/top-level classes.
- NEVER set ``parent_uri`` to the class's own URI.
- Use a SINGLE consistent URI namespace for ALL classes.
"""

_USER = """\
Extract an OWL ontology from the following text chunks. The chunks were \
parsed from a visual-heavy document. Identify all domain classes, their \
hierarchical relationships, and properties; prefer slide titles as \
hierarchy hints; cite the source chunk ids you used.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions."""

_TEMPLATE = PromptTemplate(
    key="tier1_visual_aware",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description=(
        "Visual-aware extraction prompt for PPTX decks and scanned PDFs; "
        "treats slide titles + alt text as primary hierarchy evidence."
    ),
)

register_template(_TEMPLATE)
