from __future__ import annotations

import random


def quality_band(q: float) -> str:
    if q < 0.5:
        return "low"
    if q < 0.75:
        return "mid"
    return "high"


def stratum(page: dict) -> str:
    issue = page.get("issue_label") or (page.get("source_id") or "")[:6]
    script = page.get("script") or "unknown"
    return f"{issue}|{script}|{quality_band(page['quality_score'])}"


def stratified_sample(pages: list[dict], n: int = 40, seed: int = 1979) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for p in pages:
        if p.get("quality_score") is None:
            continue
        groups.setdefault(stratum(p), []).append(p)
    if not groups:
        return []
    names = sorted(groups)
    total = sum(len(groups[s]) for s in names)
    n = min(n, total)

    # one slot per stratum (largest strata first when strata outnumber n),
    # then fill remaining slots proportionally to stratum size
    alloc = dict.fromkeys(names, 0)
    for s in sorted(names, key=lambda s: (-len(groups[s]), s))[:n]:
        alloc[s] = 1
    while sum(alloc.values()) < n:
        s = max((s for s in names if alloc[s] < len(groups[s])),
                key=lambda s: (len(groups[s]) / (alloc[s] + 1), s))
        alloc[s] += 1

    rng = random.Random(seed)
    out: list[dict] = []
    for s in names:
        pool = sorted(groups[s], key=lambda p: p["page_id"])
        out.extend(dict(p, stratum=s) for p in rng.sample(pool, alloc[s]))
    return sorted(out, key=lambda p: p["page_id"])
