# AOE sample corpora

Documents used to exercise the AOE extraction pipeline end-to-end.

Two kinds of content live here:

| Path | What it is | Licensing |
| --- | --- | --- |
| `financial/`, `healthcare/`, `supply-chain/`, `legal/` | **Synthetic** domain documents authored for AOE. Realistic in structure and vocabulary, fictional in content. | CC0 1.0 — no restriction, tracked in git. |
| `external/` | **Real** public benchmark corpora (Re-DocRED, WebNLG, CUAD, CRAFT, SEC 10-K samples). Fetched by `scripts/fetch-corpora.sh`. | Original licenses preserved (see each dataset's LICENSE). **Not tracked in git** — see `.gitignore`. |

## Why synthetic documents in-tree

- Unit/integration tests must be deterministic and runnable offline.
- Real public benchmarks (10-Ks, PubMed articles) are too large and/or carry their own licenses — they belong in `external/`, not in the repo.
- Synthetic documents let us cover the same *ontology shapes* we expect from real ones (parties, agreements, clinical concepts, commodities) without embedding copyrighted text.

## Layout

```
samples/corpora/
├── README.md                     (this file)
├── .gitignore                    (ignores external/)
├── financial/
│   ├── 10k-excerpt-acme.md       (Item 1 "Business" style)
│   ├── loan-agreement-excerpt.md (covenant-heavy)
│   └── regulatory-notice.md      (regulatory memo)
├── healthcare/
│   ├── clinical-study-abstract.md
│   ├── drug-monograph.md
│   └── clinical-guideline-summary.md
├── supply-chain/
│   ├── shipping-manifest-narrative.md
│   ├── supplier-agreement-excerpt.md
│   └── customs-bulletin.md
├── legal/
│   ├── service-agreement-clauses.md
│   ├── case-summary.md
│   └── privacy-policy-excerpt.md
└── external/                     (created by scripts/fetch-corpora.sh; gitignored)
    ├── redocred/
    ├── webnlg/
    ├── cuad/
    ├── craft/
    └── sec-edgar/
```

## Fetching external corpora

```bash
# Minimal set (~50 MB): a handful of docs per benchmark
./scripts/fetch-corpora.sh

# Full set (several GB): complete Re-DocRED, WebNLG, CUAD, CRAFT
./scripts/fetch-corpora.sh --full
```

See [`benchmarks/ontology-extraction/README.md`](../../benchmarks/ontology-extraction/README.md) for how these corpora feed the benchmark harness.

## Adding new synthetic documents

1. Put the file under the right domain folder.
2. Keep it self-contained (one file ≈ one document).
3. Prefer Markdown with explicit section headings — the chunker splits on them.
4. Use **domain vocabulary that maps to obvious ontology classes and relations** (parties, actions, agreements, measurements). That's what lets us test extraction quality.
5. Author it — don't paste from copyrighted sources. If you want to benchmark against real docs, add a fetch step in `scripts/fetch-corpora.sh` instead.
