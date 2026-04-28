# AOE ontology-extraction benchmark harness

Reproducible evaluation of AOE's extraction pipeline against public gold-standard corpora. The harness is **adapter-based** so it can run with a mock extractor in CI or against the real AOE pipeline locally.

## What it measures

Given a corpus of documents each annotated with gold **classes** (entities with types) and **relations** (typed triples `(head, relation, tail)`), the harness:

1. Runs an `ExtractionAdapter` over each document's text.
2. Computes set-overlap **precision / recall / F1** for:
   - **Classes** — does the extractor recover the gold entity set?
   - **Relations** — does the extractor recover the gold triple set?
3. Aggregates across documents and reports micro and macro averages.

All matching is exact (case-insensitive, whitespace-normalized) by default.
For domain evaluations where harmless terminology differences are expected, pass
`--alias-file` to canonicalize known label and relation aliases before scoring.

## Datasets supported

| Dataset | Loader | What it tests |
| --- | --- | --- |
| **HITL Regression** | `datasets.hitl_regression` | Curator-derived regression fixtures exported from `GET /api/v1/admin/feedback-learning`. |
| **Re-DocRED** | `datasets.redocred` | Multi-sentence relation extraction over Wikipedia articles. 96 relation types. |
| **WebNLG 2020** | `datasets.webnlg` | Structured RDF triples (DBpedia) ↔ text. |

Public corpus loaders consume the files fetched by `scripts/fetch-corpora.sh`
into `samples/corpora/external/`. HITL regression fixtures are generated from
curation feedback and can be stored under `samples/corpora/hitl-regression/`.

## Running

```bash
# Mock adapter — deterministic, no LLM, no DB. Good for CI and metric sanity checks.
python -m benchmarks.ontology_extraction.run_benchmark \
    --dataset redocred \
    --adapter mock \
    --limit 20

# Real pipeline — requires backend .venv, ArangoDB, and LLM API keys in env.
python -m benchmarks.ontology_extraction.run_benchmark \
    --dataset webnlg \
    --adapter aoe \
    --limit 50 \
    --out reports/webnlg-$(date +%Y%m%d).json

# Alias-aware scoring — still exact after canonicalization.
python -m benchmarks.ontology_extraction.run_benchmark \
    --dataset webnlg \
    --adapter aoe \
    --alias-file benchmarks/ontology_extraction/aliases/domain.json

# HITL regression fixture exported from the admin feedback-learning endpoint.
python -m benchmarks.ontology_extraction.run_benchmark \
    --dataset hitl-regression \
    --adapter aoe \
    --corpus-root samples/corpora/hitl-regression/hitl_regression.json
```

Alias files use canonical term → aliases groups:

```json
{
  "labels": {
    "customer account": ["client account", "acct"]
  },
  "relations": {
    "works at": ["employed by", "is employed by"]
  }
}
```

HITL regression fixtures use the `hitl-regression-v1` schema emitted in the
`benchmark_fixture` field of `GET /api/v1/admin/feedback-learning`. Positive
gold classes/relations are scored immediately; negative classes/relations from
reject decisions are retained in `source_meta` for review and future
negative-example scoring.

Make target:

```bash
make benchmark           # runs mock adapter on Re-DocRED dev (CI-friendly)
make benchmark-full      # real AOE adapter (requires infra)
```

## Layout

```
benchmarks/ontology_extraction/
├── README.md                      (this file)
├── __init__.py
├── metrics.py                     (precision / recall / F1 over class + relation sets)
├── run_benchmark.py               (CLI entry point)
├── adapters/
│   ├── __init__.py
│   ├── base.py                    (ExtractionAdapter protocol + shared types)
│   ├── mock.py                    (deterministic, offline)
│   └── aoe.py                     (calls backend.app.extraction.pipeline.run_pipeline)
├── datasets/
│   ├── __init__.py
│   ├── base.py                    (GoldDocument type + shared loader helpers)
│   ├── hitl_regression.py
│   ├── redocred.py
│   └── webnlg.py
└── tests/
    ├── __init__.py
    ├── test_metrics.py
    ├── test_adapters_mock.py
    └── test_datasets.py
```

## Extending

**Add a new dataset loader** — drop a module under `datasets/` that exposes `load(root: Path, limit: int | None) -> Iterable[GoldDocument]`. Register it in `run_benchmark.py`'s `DATASETS` map.

**Add a new adapter** — implement the `ExtractionAdapter` protocol from `adapters/base.py`. Register it in `run_benchmark.py`'s `ADAPTERS` map.

Both are covered by unit tests under `tests/`; new additions must ship with their own tests per the `test-what-you-touch.mdc` rule.

## Why an adapter layer

- CI runs the mock adapter — no LLM spend, deterministic metrics.
- Local benchmarking calls the real pipeline end-to-end.
- Third-party extractors (OntoGPT, REBEL, raw GPT prompts) can be plugged in for comparison without touching the metrics or dataset code.
