"""Domain-segmentation prompt (Stream 16 DD.1).

Asks the LLM to cluster document chunks into topical domains so a
multi-domain document can be detected before extraction. This prompt does
NOT extract ontology entities -- it only groups chunk ids by topic, which
downstream code turns into ``detected_domains``, per-class ``domain_tag``,
and a non-blocking ``multi_domain`` warning.
"""

from app.extraction.prompts import PromptTemplate, register_template

_SYSTEM = """\
You are a domain analyst. You will be given the text chunks of a single \
document, each with a stable ``source_chunk_id``. Your job is to group the \
chunks into the distinct TOPICAL DOMAINS (subject areas) they cover.

A "domain" is a coherent subject area, e.g. "Financial Accounting", \
"Human Resources", "Network Security", "Clinical Trials". Most documents \
cover exactly ONE domain -- in that case return a single group containing \
every chunk. Only report multiple domains when the document genuinely mixes \
unrelated subject areas.

You MUST output valid JSON matching this schema exactly:

{{
  "domains": [
    {{
      "domain": "string (short Title Case domain name, 1-4 words)",
      "chunk_ids": ["string (source_chunk_id values assigned to this domain)"],
      "confidence": 0.0-1.0
    }}
  ]
}}

Rules:
- Every ``source_chunk_id`` in the input MUST appear in exactly one group.
- Prefer FEWER domains. Do not split a single subject into sub-topics.
- Use a stable, human-readable ``domain`` name; reuse the same string for \
  all chunks of that domain.
- ``confidence`` reflects how clearly the chunks belong to that domain.
- If the document is single-domain, return exactly one group with all chunk \
  ids and a high confidence.
- Output ONLY the JSON object, no prose."""

_USER = """\
Group the following document chunks into topical domains.

--- TEXT CHUNKS ---
{chunks_text}
--- END TEXT CHUNKS ---

Return ONLY valid JSON matching the schema described in your instructions."""

_TEMPLATE = PromptTemplate(
    key="domain_segmentation",
    system_prompt=_SYSTEM,
    user_prompt=_USER,
    description="Cluster document chunks into topical domains (Stream 16 DD.1)",
)

register_template(_TEMPLATE)
