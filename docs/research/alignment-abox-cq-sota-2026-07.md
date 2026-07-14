# SOTA Research: Ontology Alignment, A-box Extraction & Competency-Question Requirements (July 2026)

**Method:** deep-research harness — 5 search angles → 23 sources fetched → 110 claims
extracted → 25 verified by 3-vote adversarial verification (24 confirmed, 1 refuted).
**Feeds:** PRD §6.17 (alignment), §6.18 (A-box extraction), §6.19 (use-case / competency
questions); implementation plan Streams 20–22.

> This is the durable, cited record behind the "SOTA basis" paragraphs in the PRD.
> Absolute F1 numbers from single-study systems (MILA/GenOM/KROMA) are author-reported
> on self-selected, mostly-biomedical OAEI tracks — treat as promising, not replicated.

---

## Executive summary

The 2023–2025 evidence points to a **hybrid, LLM-first-but-symbolically-anchored** design
for all three capabilities:

1. **Ontology alignment** — Classical OAEI systems (LogMap, AgreementMakerLight/AML) have
   **plateaued** on schema tracks; LLM+embedding **RAG matchers** (LLMs4OM, MILA, GenOM,
   KROMA) now match or beat them, especially on complex/biomedical tasks, by reserving
   costly LLM calls for **borderline pairs after embedding-based candidate retrieval**.
   OAEI's **Interactive track** and the **OAEI-LLM** hallucination benchmark provide
   ready-made evaluation harnesses for a human-in-the-loop, hallucination-controlled system.
2. **A-box extraction** — Schema/ontology-grounded LLM pipelines (**EDC** — Extract-Define-
   Canonicalize, with a trained RAG schema retriever; Wikidata-schema ontology-grounded KG
   construction) support both schema-guided and schema-free construction with
   **canonicalization and grounding** for consistency.
3. **Requirements** — **Competency-question-driven** scoping (LLM-generated CQs feeding
   ontology authoring) is the emerging automated mechanism, but the confirmed evidence is
   thinner and shows fully-automated CQ generation is **not yet reliable without human
   curation**.

**Recommended architecture:** use CQs to scope a small use-case master ontology → run
embedding-retrieval + selective-LLM alignment with symbolic incoherence repair (AML-style
modular core fragments) and an Interactive-track-style human confirmation loop → ground
A-box extraction in the merged T-box with span provenance and canonicalization.

---

## 1. Ontology alignment & merging

- **OAEI is the standard evaluation landscape** and already has two directly-relevant
  tracks: the **Interactive** track (oracle-simulated human confirmation, measuring
  F-measure vs. number of interactions — a template for efficient human confirmation) and
  the ML-friendly **Bio-ML** track (equivalence/subsumption). *[high, 3-0]*
  — https://oaei.ontologymatching.org/2024/ , https://oaei.ontologymatching.org/2024/interactive/
- **Classical schema matchers have plateaued.** OAEI 2024's own results paper: the schema-
  matching tracks gather the most participants yet show "little substantial progress …
  a performance plateau." Anatomy tops out ~0.941 F-measure, stable for years. Justifies an
  LLM-first strategy while keeping classical systems as anchors. *[high, 3-0]*
  — https://ceur-ws.org/Vol-3897/oaei2024_paper0.pdf
- **Minimally-destructive modular incoherence repair (AML core-fragment / AMLR).** Extract
  only the classes/relations needed to detect incoherences (reduces to 3.8–17% of ontology
  size; core-fragment computation <2% of repair time); AMLR makes 33–60% fewer modifications
  than LogMap and 24–40% fewer removals than ALCOMO at equivalent near-zero incoherence.
  *[high, 3-0]* (2015, still embedded in AML; the "global iterative repair is jointly
  optimal" variant was **refuted** in verification.)
  — https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0144807
- **LLM RAG matching is competitive/superior, especially on complex cases.** **LLMs4OM**
  (ESWC 2024): two-module retrieve+match, zero-shot over three representations
  (concept / concept-parent / concept-children); matches or surpasses traditional OM in
  complex cases — but **underperformed classical methods on Bio-ML**, so classical anchors
  remain necessary. *[high, 3-0]* — https://arxiv.org/abs/2404.10317
- **Cost-efficient hybrid pattern (adopt this): MILA.** A retrieve-identify-prompt pipeline
  inside a prioritized depth-first search that resolves most correspondences via
  embedding/heuristics and reserves LLM calls only for borderline pairs — **~94% fewer LLM
  comparisons**; highest F-measure in 4/5 unsupervised OAEI 2023/2024 biomedical tasks.
  Maps directly to ArangoDB vector-search + selective-LLM. *[high, 3-0]*
  — https://arxiv.org/abs/2501.11441
- **GenOM (concrete recipe).** Five stages: extract → LLM NL concept-definition generation →
  embedding retrieval (OpenAI text-embedding-3-small + FAISS HNSW cosine top-k) → LLM
  equivalence judgement → fusion. 0.901 F1 on NCIT-DOID, 0.774 on SNOMED-NCIT; +9.88% mean
  F1 over LogMap-LLM (GPT-4o). *[high, 3-0]* — https://arxiv.org/html/2508.10703v2
- **KROMA.** RAG (structural+lexical+definitional context) + bisimilarity matching +
  lightweight refinement to prune candidates and cut LLM overhead; strong F1 across six
  datasets. *[high, 3-0]* — https://arxiv.org/pdf/2507.14032
- **Hallucination control has a benchmark: OAEI-LLM** (and temporal follow-up OAEI-LLM-T) —
  extends OAEI datasets to classify LLM hallucination types (e.g. "Missing") in matching.
  *[high, 3-0]* — https://arxiv.org/abs/2409.14038 , https://arxiv.org/abs/2503.21813
- **Embeddings lead complex/instance matching.** OAEI 2024: integrating LLM-generated
  embeddings into the CANARD complex matcher raised precision/F-measure up to 45% over the
  2018 baseline; in Bio-ML equivalence, ML/embedding systems (BioGITOM, HybridOM, BERTMap)
  matched or beat symbolic LogMap variants — but **no single system wins everywhere**, so an
  ensemble with human adjudication on disagreements is warranted. *[high, 3-0]*
  — https://ceur-ws.org/Vol-3897/oaei2024_paper0.pdf
- **Efficient human confirmation: DualLoop** — active learning for interactive matching cuts
  expected query cost to find 90% of matches by >50% vs prior active-learning.
  — https://arxiv.org/abs/2404.07663 , https://oaei.ontologymatching.org/2024/results/interactive/index.htm

## 2. Assertion-graph (A-box) extraction

- **EDC — Extract, Define, Canonicalize** (EMNLP 2024) is the reference framework: three
  phases (open IE extract → define schema → canonicalize entities/relations) supporting
  **both schema-guided and schema-free** construction, with a **trained schema retriever**
  that RAG-injects only text-relevant schema elements — enabling grounding in a large
  ontology without exceeding context (WebNLG Partial F1 0.783→0.820; REBEL 0.546→0.601 with
  GPT-4). *[high, 3-0]* **Caveat:** EDC's "schema" is relation-type definitions, looser than
  a full OWL/SHACL T-box. — https://arxiv.org/abs/2404.03868
- **Ontology-grounded LLM KG construction** is validated as a pattern where A-box generation
  is grounded in an ontology for consistency/interpretability; one 2024 pipeline authors the
  ontology via LLM-generated competency questions + extracted relations aligned to the
  Wikidata schema, then grounds KG generation in that ontology — linking the CQ-requirements
  capability to the A-box capability. *[high, 3-0]* — https://arxiv.org/abs/2412.20942

## 3. Use-case / competency-question-driven requirements

- **Bench4KE** — benchmark for automated CQ generation (curated gold standard of 843 CQs
  across 17 real-world ontology-engineering projects); designed to extend to SPARQL
  generation and ontology testing. — https://arxiv.org/pdf/2505.24554
- **NeOn-GPT** operationalizes the NeOn methodology as an LLM multi-step pipeline:
  requirement specification → competency-question generation → conceptualization → reuse →
  implementation → formal modeling → population → documentation.
  — https://www.semantic-web-journal.net/system/files/swj4014.pdf
- **FrODO** converts NL competency questions into domain-ontology drafts via frame semantics
  over the FRED semantic parser's RDF output. — https://arxiv.org/pdf/2206.02485
- **VSPO** — dataset + fine-tuned model for CQ generation that detects **semantic pitfalls**
  (e.g. misuse of `allValuesFrom`) rule-based methods miss. — https://arxiv.org/pdf/2511.07991
- **Reliability caveat (load-bearing):** measured precision of automated CQ generation is
  generally **low**; one fully-automated pipeline yielded only ~25% in-scope and ~45%
  unproblematic-quality questions. **→ CQs must be human-authored, LLM-assisted, and
  human-curated, never auto-committed.** — https://aclanthology.org/2025.ldk-1.15.pdf ,
  https://link.springer.com/chapter/10.1007/978-3-031-78952-6_7

---

## Caveats (from verification)

1. Strongest alignment numbers (MILA/GenOM/KROMA) are **author-reported** on self-selected,
   mostly-biomedical tracks — not audited OAEI leaderboard placements. Expect lower, less
   consistent performance on general/enterprise/ArangoDB-derived ontologies.
2. LLMs do **not** uniformly beat classical systems (LLMs4OM underperformed on Bio-ML;
   best performers vary by task) — keep classical anchors + human adjudication.
3. AML core-fragment/AMLR repair evidence is **2015** — established and still used, but
   predates the 2023–2025 window.
4. One claim was **refuted**: global iterative conflict-set repair is *not* provably jointly
   optimal — don't assume repair-algorithm optimality.
5. EDC's "schema" is relation-type-level, not full OWL/SHACL — AOE must add class-hierarchy +
   constraint grounding on top.
6. **Coverage gap:** the confirmed evidence is heavily weighted toward alignment; A-box
   multi-domain instance routing and span-level provenance, and automated CQ→SPARQL/AQL
   coverage checking, are **under-evidenced** and were designed from AOE's existing infra
   (Stream 16 `domain_tag`, `extracted_from` provenance) rather than a confirmed source.

## Open questions

1. How do MILA/GenOM/KROMA perform **outside** biomedical/OAEI tracks on enterprise or
   ArangoDB-derived ontologies, and is there an independent (non-author) audited benchmark?
2. What is the concrete SOTA for **routing A-box instances to the correct domain ontology**
   in multi-domain sets, and for attaching span-level provenance? (Neither confirmed.)
3. Which requirements methodology has demonstrated **automated CQ-to-query coverage
   checking** working uniformly across relational, semi-structured, graph, and unstructured
   sources?
4. How best to integrate 2015-era symbolic incoherence repair (AML) with **LLM-generated**
   equivalence axioms to yield a coherent merged master?

---

## Recommended AOE design (→ PRD §6.17–§6.19)

- **Alignment (§6.17):** embedding retrieval over ArangoDB vector search (embeddings enriched
  with LLM-generated definitions, GenOM-style) → multi-signal scoring (reuse §6.7 ER scorer,
  2→N) → selective LLM adjudication of borderline pairs (MILA/KROMA) → conflict *resolution*
  into a master with `owl:equivalentClass` + provenance → minimally-destructive modular
  repair (AML core-fragment via the §6.16 rule engine) → bounded human confirmation
  (DualLoop / OAEI-Interactive, ~2%) → hallucination check (OAEI-LLM) → OAEI-style eval.
  Classical (LogMap/AML) as anchor/ensemble, not the engine.
- **A-box (§6.18):** EDC-style schema-grounded extraction with a RAG schema retriever;
  canonicalize via §6.7 ER; span-level `extracted_from` provenance; multi-domain routing via
  the Stream 16 `domain_tag`; validate against §6.14 constraints.
- **Requirements (§6.19):** human-authored, LLM-assisted, human-curated CQs (ORSD / NeOn);
  formalize CQ→AQL; inject CQ terms to scope extraction across all source adapters; run CQ
  queries to validate coverage; route gaps to §6.16; gate releases via Stream 19.
