"""Part 4b: probabilistic near-duplicate detection -> human fold candidates.

Swappable backend: Azure OpenAI embeddings + cosine when an embeddings deployment is configured,
otherwise a deterministic token-set (Jaccard) similarity that keeps the offline pipeline working and
serves as the documented fallback. Exact duplicates are already removed deterministically upstream;
this finds rules that are only *similar* (slight wording differences) for a human to fold or keep.
"""

from __future__ import annotations

import math
import re
from typing import Any

from .config import Settings
from .consolidation_rules import rule_signature_text
from .llm_client import LLMClient


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _jaccard(first: set[str], second: set[str]) -> float:
    union = first | second
    return len(first & second) / len(union) if union else 0.0


def _cosine(first: list[float], second: list[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


def _use_embeddings(settings: Settings) -> bool:
    return settings.llm_mode == "azure" and bool(settings.azure_openai_embedding_deployment)


def _similarity_matrix(
    texts: list[str], client: LLMClient, settings: Settings
) -> list[list[float]]:
    count = len(texts)
    if _use_embeddings(settings):
        vectors = client.embed(texts)
        return [[_cosine(vectors[i], vectors[j]) for j in range(count)] for i in range(count)]
    token_sets = [_tokens(text) for text in texts]
    return [[_jaccard(token_sets[i], token_sets[j]) for j in range(count)] for i in range(count)]


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, node: int) -> int:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, first: int, second: int) -> None:
        self.parent[self.find(first)] = self.find(second)


def find_candidates(
    rules: list[dict[str, Any]], client: LLMClient, settings: Settings
) -> list[dict[str, Any]]:
    """Cluster near-duplicate rules into fold candidates above the similarity threshold."""
    count = len(rules)
    if count < 2:
        return []
    texts = [rule_signature_text(rule) for rule in rules]
    matrix = _similarity_matrix(texts, client, settings)
    threshold = settings.similarity_threshold

    union_find = _UnionFind(count)
    best: dict[tuple[int, int], float] = {}
    for i in range(count):
        for j in range(i + 1, count):
            score = matrix[i][j]
            if score >= threshold:
                union_find.union(i, j)
                best[(i, j)] = score

    clusters: dict[int, list[int]] = {}
    for index in range(count):
        clusters.setdefault(union_find.find(index), []).append(index)

    candidates: list[dict[str, Any]] = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        pair_scores = [best[(i, j)] for i in members for j in members if i < j and (i, j) in best]
        score = round(max(pair_scores), 3) if pair_scores else threshold
        member_rules = sorted((rules[index] for index in members), key=lambda r: r["rule_id"])
        candidates.append(
            {
                "candidate_id": f"cand-{len(candidates) + 1:02d}",
                "similarity": score,
                "decision": "keep_separate",
                "fold_into": None,
                "members": [
                    {
                        "rule_id": rule["rule_id"],
                        "rule_name": rule["rule_name"],
                        "policy_id": rule["policy_source"].get("policy_id", ""),
                    }
                    for rule in member_rules
                ],
            }
        )
    candidates.sort(key=lambda candidate: candidate["candidate_id"])
    return candidates
