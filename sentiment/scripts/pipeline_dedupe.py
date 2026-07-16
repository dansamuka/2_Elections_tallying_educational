"""Stage 2: deduplicate (Section 7.2, test 5: duplicate waves affect volume,
never the unique-source metric)."""
from collections import defaultdict
from lib.text_utils import token_set, jaccard_similarity, stable_author_bucket


def run(items: list, run_salt: str, near_dup_threshold: float = 0.82) -> list:
    """Group exact duplicates by content_hash, then merge near-duplicates
    within each source_type via token-set similarity. Returns one canonical
    item per cluster with `frequency` (repost count) and `author_buckets`
    (set of salted author hashes seen in the cluster, for source-diversity
    counting - never the raw author id itself).
    """
    # Step A: exact-duplicate grouping by hash, scoped per source_type so a
    # news headline and an unrelated tweet never collide on hash alone.
    exact_groups = defaultdict(list)
    for item in items:
        key = (item.get("source_type"), item["content_hash"])
        exact_groups[key].append(item)

    canonical_by_group = {}
    for key, group in exact_groups.items():
        canonical = group[0]
        canonical["frequency"] = len(group)
        canonical["author_buckets"] = {
            stable_author_bucket(g.get("author_ref", ""), run_salt) for g in group if g.get("author_ref")
        }
        canonical_by_group[key] = canonical

    canonicals = list(canonical_by_group.values())

    # Step B: near-duplicate merge within each source_type bucket. O(n^2)
    # on canonicals only (already collapsed exact dupes), which keeps this
    # tractable for a 15-minute refresh window's worth of items.
    merged = []
    used = [False] * len(canonicals)
    token_cache = [token_set(c["normalized_text"]) for c in canonicals]

    for i, item in enumerate(canonicals):
        if used[i]:
            continue
        cluster_freq = item["frequency"]
        cluster_authors = set(item["author_buckets"])
        for j in range(i + 1, len(canonicals)):
            if used[j] or canonicals[j].get("source_type") != item.get("source_type"):
                continue
            if jaccard_similarity(token_cache[i], token_cache[j]) >= near_dup_threshold:
                used[j] = True
                cluster_freq += canonicals[j]["frequency"]
                cluster_authors |= canonicals[j]["author_buckets"]
        item["frequency"] = cluster_freq
        item["author_buckets"] = cluster_authors
        item["independent_source_count"] = len(cluster_authors)
        merged.append(item)
        used[i] = True

    return merged
