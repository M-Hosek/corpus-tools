from __future__ import annotations


def strip_layout(text: str) -> str:
    """Remove all whitespace: line breaks and spacing are layout, not content."""
    return "".join(text.split())


def cer(ref: str, hyp: str) -> dict:
    """Character error rate of hyp against ref, whitespace-insensitive.

    Returns cer, distance, and substitution/deletion/insertion counts.
    Deletion = ref char missing from hyp; insertion = extra char in hyp.
    """
    r, h = strip_layout(ref), strip_layout(hyp)
    if not r:
        raise ValueError("empty reference text")
    n = len(h)
    # rolling rows: distance plus S/D/I counts along the optimal path
    dist = list(range(n + 1))
    sub = [0] * (n + 1)
    dele = [0] * (n + 1)
    ins = list(range(n + 1))
    for i in range(1, len(r) + 1):
        pdist, psub, pdele, pins = dist, sub, dele, ins
        dist = [i] + [0] * n
        sub = [0] * (n + 1)
        dele = [i] + [0] * n
        ins = [0] * (n + 1)
        rc = r[i - 1]
        for j in range(1, n + 1):
            if rc == h[j - 1]:
                dist[j], sub[j], dele[j], ins[j] = (
                    pdist[j - 1], psub[j - 1], pdele[j - 1], pins[j - 1])
                continue
            a, b, c = pdist[j - 1], pdist[j], dist[j - 1]
            if a <= b and a <= c:            # substitution
                dist[j] = a + 1
                sub[j], dele[j], ins[j] = psub[j - 1] + 1, pdele[j - 1], pins[j - 1]
            elif b <= c:                     # deletion (ref char dropped)
                dist[j] = b + 1
                sub[j], dele[j], ins[j] = psub[j], pdele[j] + 1, pins[j]
            else:                            # insertion (extra hyp char)
                dist[j] = c + 1
                sub[j], dele[j], ins[j] = sub[j - 1], dele[j - 1], ins[j - 1] + 1
    return {"cer": dist[n] / len(r), "distance": dist[n], "sub": sub[n],
            "dele": dele[n], "ins": ins[n], "ref_chars": len(r)}
