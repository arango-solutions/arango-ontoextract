"""Entity Resolution pipeline service.

Configures and executes the ``arango-entity-resolution`` pipeline for
ontology class deduplication with AOE-specific topological scoring.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.services.er_topology import compute_topological_similarity
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


class ERRunStatus(StrEnum):
    PENDING = "pending"
    BLOCKING = "blocking"
    SCORING = "scoring"
    CLUSTERING = "clustering"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ERFieldConfig:
    """Configuration for a single field in similarity scoring."""

    field_name: str
    weight: float
    algorithm: str  # "jaro_winkler" | "cosine" | "exact" | "levenshtein"


@dataclass
class ERPipelineConfig:
    """Configuration for the entity resolution pipeline."""

    collection: str = "ontology_classes"
    ontology_id: str | None = None
    blocking_strategies: list[str] = field(
        default_factory=lambda: ["bm25", "vector"]
    )
    field_configs: list[ERFieldConfig] = field(default_factory=lambda: [
        ERFieldConfig(field_name="label", weight=0.4, algorithm="jaro_winkler"),
        ERFieldConfig(field_name="description", weight=0.3, algorithm="cosine"),
        ERFieldConfig(field_name="uri", weight=0.2, algorithm="exact"),
    ])
    topological_weight: float = 0.1
    similarity_threshold: float = 0.7
    vector_similarity_threshold: float = 0.85
    wcc_backend: str = "auto"

    def to_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "ontology_id": self.ontology_id,
            "blocking_strategies": self.blocking_strategies,
            "field_configs": [
                {"field_name": f.field_name, "weight": f.weight, "algorithm": f.algorithm}
                for f in self.field_configs
            ],
            "topological_weight": self.topological_weight,
            "similarity_threshold": self.similarity_threshold,
            "vector_similarity_threshold": self.vector_similarity_threshold,
            "wcc_backend": self.wcc_backend,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ERPipelineConfig:
        field_configs = [
            ERFieldConfig(**fc) for fc in data.get("field_configs", [])
        ]
        return cls(
            collection=data.get("collection", "ontology_classes"),
            ontology_id=data.get("ontology_id"),
            blocking_strategies=data.get("blocking_strategies", ["bm25", "vector"]),
            field_configs=field_configs if field_configs else cls().field_configs,
            topological_weight=data.get("topological_weight", 0.1),
            similarity_threshold=data.get("similarity_threshold", 0.7),
            vector_similarity_threshold=data.get("vector_similarity_threshold", 0.85),
            wcc_backend=data.get("wcc_backend", "auto"),
        )


@dataclass
class ERRunResult:
    """Result of an ER pipeline run."""

    run_id: str
    status: ERRunStatus
    candidate_count: int = 0
    cluster_count: int = 0
    duration_seconds: float = 0.0
    config: ERPipelineConfig | None = None
    error: str | None = None


_active_config = ERPipelineConfig()
_run_store: dict[str, ERRunResult] = {}


def get_config() -> ERPipelineConfig:
    """Return the current ER pipeline configuration."""
    return _active_config


def update_config(config_data: dict[str, Any]) -> ERPipelineConfig:
    """Update the ER pipeline configuration."""
    global _active_config
    _active_config = ERPipelineConfig.from_dict(config_data)
    return _active_config


def configure_blocking(config: ERPipelineConfig) -> dict[str, Any]:
    """Set up blocking strategies for candidate pair generation.

    Returns a dict describing the configured blocking pipeline.
    """
    strategies = []
    for strategy_name in config.blocking_strategies:
        if strategy_name == "bm25":
            strategies.append({
                "type": "BM25BlockingStrategy",
                "fields": ["label", "description"],
                "view": "ontology_classes_search",
                "top_k": 20,
            })
        elif strategy_name == "vector":
            strategies.append({
                "type": "VectorBlockingStrategy",
                "field": "embedding",
                "threshold": config.vector_similarity_threshold,
                "top_k": 10,
            })
        elif strategy_name == "graph_traversal":
            strategies.append({
                "type": "GraphTraversalBlockingStrategy",
                "edge_collections": ["subclass_of", "has_property"],
                "max_depth": 2,
            })

    return {
        "orchestrator": "MultiStrategyOrchestrator",
        "mode": "union",
        "strategies": strategies,
    }


def configure_scoring(config: ERPipelineConfig) -> dict[str, Any]:
    """Set up weighted field similarity scoring.

    Returns a dict describing the scoring configuration.
    """
    field_scorers = []
    for fc in config.field_configs:
        field_scorers.append({
            "field": fc.field_name,
            "algorithm": fc.algorithm,
            "weight": fc.weight,
        })

    return {
        "type": "WeightedFieldSimilarity",
        "fields": field_scorers,
        "topological_weight": config.topological_weight,
        "threshold": config.similarity_threshold,
    }


def run_er_pipeline(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    config: ERPipelineConfig | None = None,
) -> ERRunResult:
    """Execute the full ER pipeline: blocking -> scoring -> clustering -> golden records.

    Uses ``arango-entity-resolution`` library for the core pipeline and adds
    AOE-specific topological scoring as an additional dimension.
    """
    if db is None:
        db = get_db()

    if config is None:
        config = _active_config

    config.ontology_id = ontology_id
    run_id = f"er_{uuid.uuid4().hex[:12]}"
    start = time.time()

    run_result = ERRunResult(
        run_id=run_id,
        status=ERRunStatus.PENDING,
        config=config,
    )
    _run_store[run_id] = run_result

    try:
        run_result.status = ERRunStatus.BLOCKING
        candidates = _execute_blocking(db, ontology_id, config)

        run_result.status = ERRunStatus.SCORING
        scored_pairs = _execute_scoring(db, candidates, config)

        run_result.status = ERRunStatus.CLUSTERING
        clusters = _execute_clustering(db, scored_pairs, run_id)

        run_result.status = ERRunStatus.COMPLETE
        run_result.candidate_count = len(scored_pairs)
        run_result.cluster_count = len(clusters)
        run_result.duration_seconds = round(time.time() - start, 3)

        log.info(
            "er pipeline completed",
            extra={
                "run_id": run_id,
                "candidates": len(scored_pairs),
                "clusters": len(clusters),
                "duration": run_result.duration_seconds,
            },
        )

    except Exception as exc:
        run_result.status = ERRunStatus.FAILED
        run_result.error = str(exc)
        run_result.duration_seconds = round(time.time() - start, 3)
        log.exception("er pipeline failed", extra={"run_id": run_id})

    return run_result


def get_run_status(run_id: str) -> ERRunResult | None:
    """Get the status of an ER pipeline run."""
    return _run_store.get(run_id)


def get_candidates(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    min_score: float = 0.0,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return merge candidate pairs with similarity scores."""
    if db is None:
        db = get_db()

    if not db.has_collection("similarTo"):
        return []

    return list(
        run_aql(db,
            """\
FOR e IN similarTo
  FILTER e.ontology_id == @oid
  FILTER e.combined_score >= @min_score
  SORT e.combined_score DESC
  LIMIT @offset, @limit
  LET source = DOCUMENT(e._from)
  LET target = DOCUMENT(e._to)
  RETURN {
    pair_id: e._key,
    source_key: source._key,
    source_label: source.label,
    source_uri: source.uri,
    target_key: target._key,
    target_label: target.label,
    target_uri: target.uri,
    combined_score: e.combined_score,
    field_scores: e.field_scores,
    topological_score: e.topological_score
  }""",
            bind_vars={
                "oid": ontology_id,
                "min_score": min_score,
                "limit": limit,
                "offset": offset,
            },
        )
    )


def get_clusters(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """Return entity clusters from WCC analysis."""
    if db is None:
        db = get_db()

    if not db.has_collection("entity_clusters"):
        return []

    return list(
        run_aql(db,
            """\
FOR cluster IN entity_clusters
  FILTER cluster.ontology_id == @oid
  SORT cluster.size DESC
  RETURN cluster""",
            bind_vars={"oid": ontology_id},
        )
    )


def explain_match(
    db: StandardDatabase | None = None,
    *,
    key1: str,
    key2: str,
) -> dict[str, Any]:
    """Return detailed field-by-field similarity breakdown for a pair."""
    if db is None:
        db = get_db()

    class_1 = _get_class_doc(db, key1)
    class_2 = _get_class_doc(db, key2)

    if not class_1 or not class_2:
        return {"error": "One or both classes not found", "key1": key1, "key2": key2}

    field_scores: dict[str, float] = {}

    label_1 = class_1.get("label", "")
    label_2 = class_2.get("label", "")
    field_scores["label_jaro_winkler"] = _jaro_winkler_sim(label_1, label_2)

    desc_1 = class_1.get("description", "")
    desc_2 = class_2.get("description", "")
    field_scores["description_token_overlap"] = _token_overlap(desc_1, desc_2)

    uri_1 = class_1.get("uri", "")
    uri_2 = class_2.get("uri", "")
    field_scores["uri_exact"] = 1.0 if uri_1 == uri_2 else 0.0

    topo_score = compute_topological_similarity(db, class_key_1=key1, class_key_2=key2)
    field_scores["topological"] = topo_score

    combined = (
        0.4 * field_scores["label_jaro_winkler"]
        + 0.3 * field_scores["description_token_overlap"]
        + 0.2 * field_scores["uri_exact"]
        + 0.1 * field_scores["topological"]
    )

    return {
        "key1": key1,
        "key2": key2,
        "class_1": {"label": label_1, "uri": uri_1},
        "class_2": {"label": label_2, "uri": uri_2},
        "field_scores": field_scores,
        "combined_score": round(combined, 4),
    }


def execute_merge(
    db: StandardDatabase | None = None,
    *,
    source_key: str,
    target_key: str,
    strategy: str = "most_complete",
) -> dict[str, Any]:
    """Execute a merge for a candidate pair.

    The source entity is deprecated and its data merged into the target
    entity via golden record creation.
    """
    if db is None:
        db = get_db()

    source = _get_class_doc(db, source_key)
    target = _get_class_doc(db, target_key)

    if not source or not target:
        raise ValueError("Source or target class not found")

    merged_data = _create_golden_record(source, target, strategy)

    from app.db.ontology_repo import update_class
    from app.services.temporal import expire_entity

    updated = update_class(
        db,
        key=target_key,
        data=merged_data,
        change_summary=f"Merged with {source_key} via ER ({strategy})",
    )

    expire_entity(db, collection="ontology_classes", key=source_key)

    if db.has_collection("golden_records"):
        db.collection("golden_records").insert({
            "source_key": source_key,
            "target_key": target_key,
            "strategy": strategy,
            "merged_at": time.time(),
            "merged_data": merged_data,
        })

    return {
        "target_key": target_key,
        "source_key": source_key,
        "strategy": strategy,
        "merged_version": updated,
    }


def get_cross_tier_candidates(
    db: StandardDatabase | None = None,
    *,
    local_ontology_id: str,
    domain_ontology_id: str,
    min_score: float = 0.5,
) -> list[dict[str, Any]]:
    """Find duplicate candidates across local and domain tiers."""
    if db is None:
        db = get_db()

    if not db.has_collection("ontology_classes"):
        return []

    local_classes = list(
        run_aql(db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @local_oid
  FILTER cls.expired == @never
  RETURN cls""",
            bind_vars={"local_oid": local_ontology_id, "never": NEVER_EXPIRES},
        )
    )

    domain_classes = list(
        run_aql(db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @domain_oid
  FILTER cls.expired == @never
  RETURN cls""",
            bind_vars={"domain_oid": domain_ontology_id, "never": NEVER_EXPIRES},
        )
    )

    candidates: list[dict[str, Any]] = []
    for local_cls in local_classes:
        for domain_cls in domain_classes:
            label_sim = _jaro_winkler_sim(
                local_cls.get("label", ""), domain_cls.get("label", "")
            )
            desc_sim = _token_overlap(
                local_cls.get("description", ""), domain_cls.get("description", "")
            )
            combined = 0.6 * label_sim + 0.4 * desc_sim
            if combined >= min_score:
                candidates.append({
                    "local_key": local_cls["_key"],
                    "local_label": local_cls.get("label", ""),
                    "domain_key": domain_cls["_key"],
                    "domain_label": domain_cls.get("label", ""),
                    "combined_score": round(combined, 4),
                    "label_similarity": round(label_sim, 4),
                    "description_similarity": round(desc_sim, 4),
                })

    candidates.sort(key=lambda c: c["combined_score"], reverse=True)
    return candidates


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _execute_blocking(
    db: StandardDatabase,
    ontology_id: str,
    config: ERPipelineConfig,
) -> list[tuple[str, str]]:
    """Generate candidate pairs via blocking strategies."""
    if not db.has_collection(config.collection):
        return []

    classes = list(
        run_aql(db,
            """\
FOR cls IN @@col
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN {key: cls._key, label: cls.label, uri: cls.uri}""",
            bind_vars={
                "@col": config.collection,
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )

    pairs: set[tuple[str, str]] = set()
    label_groups: dict[str, list[str]] = {}

    for cls in classes:
        label_lower = cls.get("label", "").lower().strip()
        tokens = set(label_lower.split())
        for token in tokens:
            if len(token) > 2:
                label_groups.setdefault(token, []).append(cls["key"])

    for _token, keys in label_groups.items():
        for i in range(len(keys)):
            for j in range(i + 1, len(keys)):
                pair = (min(keys[i], keys[j]), max(keys[i], keys[j]))
                pairs.add(pair)

    return list(pairs)


def _execute_scoring(
    db: StandardDatabase,
    candidates: list[tuple[str, str]],
    config: ERPipelineConfig,
) -> list[dict[str, Any]]:
    """Score candidate pairs with weighted field similarity + topological."""
    scored: list[dict[str, Any]] = []

    for key1, key2 in candidates:
        class_1 = _get_class_doc(db, key1)
        class_2 = _get_class_doc(db, key2)
        if not class_1 or not class_2:
            continue

        field_scores: dict[str, float] = {}
        weighted_sum = 0.0

        for fc in config.field_configs:
            val1 = str(class_1.get(fc.field_name, ""))
            val2 = str(class_2.get(fc.field_name, ""))

            if fc.algorithm == "jaro_winkler":
                sim = _jaro_winkler_sim(val1, val2)
            elif fc.algorithm == "exact":
                sim = 1.0 if val1 == val2 else 0.0
            elif fc.algorithm == "cosine":
                sim = _token_overlap(val1, val2)
            else:
                sim = _jaro_winkler_sim(val1, val2)

            field_scores[fc.field_name] = round(sim, 4)
            weighted_sum += fc.weight * sim

        topo_score = compute_topological_similarity(
            db, class_key_1=key1, class_key_2=key2
        )
        field_scores["topological"] = topo_score
        weighted_sum += config.topological_weight * topo_score

        combined = round(weighted_sum, 4)

        if combined >= config.similarity_threshold:
            edge_doc = {
                "_from": f"ontology_classes/{key1}",
                "_to": f"ontology_classes/{key2}",
                "combined_score": combined,
                "field_scores": field_scores,
                "topological_score": topo_score,
                "ontology_id": config.ontology_id,
            }

            if db.has_collection("similarTo"):
                db.collection("similarTo").insert(edge_doc)

            scored.append({
                "key1": key1,
                "key2": key2,
                "combined_score": combined,
                "field_scores": field_scores,
            })

    return scored


def _execute_clustering(
    db: StandardDatabase,
    scored_pairs: list[dict[str, Any]],
    run_id: str,
) -> list[dict[str, Any]]:
    """Group candidate pairs into clusters via Union-Find (WCC)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for pair in scored_pairs:
        k1, k2 = pair["key1"], pair["key2"]
        parent.setdefault(k1, k1)
        parent.setdefault(k2, k2)
        union(k1, k2)

    cluster_map: dict[str, list[str]] = {}
    for key in parent:
        root = find(key)
        cluster_map.setdefault(root, []).append(key)

    clusters: list[dict[str, Any]] = []
    for members in cluster_map.values():
        if len(members) < 2:
            continue

        cluster_doc: dict[str, Any] = {
            "run_id": run_id,
            "members": members,
            "size": len(members),
            "ontology_id": scored_pairs[0].get("ontology_id") if scored_pairs else None,
        }

        if db.has_collection("entity_clusters"):
            result = cast(
                "dict[str, Any]",
                db.collection("entity_clusters").insert(cluster_doc, return_new=True),
            )
            cluster_doc = result["new"]

        clusters.append(cluster_doc)

    return clusters


def _get_class_doc(db: StandardDatabase, key: str) -> dict[str, Any] | None:
    if not db.has_collection("ontology_classes"):
        return None

    results = list(
        run_aql(db,
            "FOR cls IN ontology_classes"
            " FILTER cls._key == @k FILTER cls.expired == @never"
            " LIMIT 1 RETURN cls",
            bind_vars={"k": key, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


def _jaro_winkler_sim(s1: str, s2: str) -> float:
    """Simplified Jaro-Winkler similarity."""
    if not s1 or not s2:
        return 0.0
    if s1 == s2:
        return 1.0

    s1_lower, s2_lower = s1.lower(), s2.lower()
    if s1_lower == s2_lower:
        return 1.0

    len1, len2 = len(s1_lower), len(s2_lower)
    match_distance = max(len1, len2) // 2 - 1
    if match_distance < 0:
        match_distance = 0

    s1_matches = [False] * len1
    s2_matches = [False] * len2
    matches = 0
    transpositions = 0

    for i in range(len1):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len2)
        for j in range(start, end):
            if s2_matches[j] or s1_lower[i] != s2_lower[j]:
                continue
            s1_matches[i] = True
            s2_matches[j] = True
            matches += 1
            break

    if matches == 0:
        return 0.0

    k = 0
    for i in range(len1):
        if not s1_matches[i]:
            continue
        while not s2_matches[k]:
            k += 1
        if s1_lower[i] != s2_lower[k]:
            transpositions += 1
        k += 1

    jaro = (matches / len1 + matches / len2 + (matches - transpositions / 2) / matches) / 3

    prefix_len = 0
    for i in range(min(4, min(len1, len2))):
        if s1_lower[i] == s2_lower[i]:
            prefix_len += 1
        else:
            break

    return jaro + prefix_len * 0.1 * (1 - jaro)


def _token_overlap(text1: str, text2: str) -> float:
    """Token-level overlap similarity (Jaccard on words)."""
    if not text1 or not text2:
        return 0.0
    tokens1 = set(text1.lower().split())
    tokens2 = set(text2.lower().split())
    if not tokens1 or not tokens2:
        return 0.0
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    return len(intersection) / len(union)


def _create_golden_record(
    source: dict[str, Any],
    target: dict[str, Any],
    strategy: str,
) -> dict[str, Any]:
    """Create a merged record using the specified strategy."""
    if strategy == "most_complete":
        merged = {}
        for field_name in ("label", "description", "uri", "tier", "org_id", "status"):
            src_val = source.get(field_name)
            tgt_val = target.get(field_name)
            if tgt_val and src_val:
                merged[field_name] = tgt_val if len(str(tgt_val)) >= len(str(src_val)) else src_val
            else:
                merged[field_name] = tgt_val or src_val
        return merged
    elif strategy == "newest":
        return {
            k: v for k, v in target.items()
            if not k.startswith("_") and k not in ("created", "expired", "version", "ttlExpireAt")
        }
    else:
        return {
            k: v for k, v in target.items()
            if not k.startswith("_") and k not in ("created", "expired", "version", "ttlExpireAt")
        }
