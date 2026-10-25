"""Product-name resolution + Malaysia remap helpers.

Why this exists: Shopee now redirects many product links to the
opaque /opaanlp/<shop>/<item> form, which carries no name slug, so
~250 items arrived with product_name NULL and generic captions.
Names must come from somewhere else:

- ID items: the logged-in Shopee browser session (account "isengnemu",
  established 2026-10-23, re-confirmed alive 2026-10-25; cookies survive
  in the browser profile). NOTE: the in-session item API
  (api/v4/item/get) returns error 90309999 even with the session alive,
  so the working route is the product page itself (h1/title).
  A browser task fetches batches and reports {item_id: name}; this
  module applies those reports.
- MY items: no MY login exists (per-country accounts), so their names
  come from manual rename in the dashboard until a MY session exists.
  Once a MY item HAS a name, the remap step searches that name on
  Shopee ID and swaps the link to the best-matching ID product
  (video reused as-is).

apply_names() never renames package directories (they are keyed by
the original slug) — it updates the display name, links.txt, and the
name_source audit column only.
"""

import difflib
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def clean_name(name: str) -> str | None:
    """Normalise a reported product name; reject obvious non-names."""
    if not name:
        return None
    name = re.sub(r"\s+", " ", str(name)).strip()
    if len(name) < 3:
        return None
    # Shopee chrome that sometimes leaks into titles
    for junk in ("shopee indonesia", "jual ", "harga "):
        if name.lower().startswith(junk) and len(name) < 20:
            return None
    return name


def apply_names(conn, mapping: dict[int, str],
                source: str) -> tuple[int, list[int]]:
    """Write names to DB + links.txt. Returns (applied, skipped_ids)."""
    applied, skipped = 0, []
    for item_id, raw_name in mapping.items():
        name = clean_name(raw_name)
        row = conn.execute("SELECT slug FROM items WHERE id = ?",
                           (item_id,)).fetchone()
        if not row or not name:
            skipped.append(item_id)
            continue
        conn.execute("UPDATE items SET product_name = ?, name_source = ? "
                     "WHERE id = ?", (name, source, item_id))
        pkg = ROOT / "storage" / "ready" / f"{item_id}-{row['slug']}"
        links = pkg / "links.txt"
        if links.exists():
            txt = links.read_text()
            txt = re.sub(r"^product_name:.*$",
                         f"product_name: {name}", txt, flags=re.M)
            links.write_text(txt)
        applied += 1
    conn.commit()
    return applied, skipped


def title_similarity(a: str, b: str) -> float:
    """0..1 similarity for MY->ID best-match picking."""
    norm = lambda s: re.sub(r"[^a-z0-9 ]", " ",
                            s.lower()).split()
    wa, wb = norm(a or ""), norm(b or "")
    if not wa or not wb:
        return 0.0
    return difflib.SequenceMatcher(None, wa, wb).ratio()


def pick_best_match(name: str, candidates: list[dict]) -> dict | None:
    """Pick the ID-search candidate whose title best matches the name.

    candidates: [{title, product_url, shop_id, item_id, price}].
    Requires a minimum similarity so a bad search never swaps in a
    random product."""
    best, best_score = None, 0.0
    for c in candidates:
        score = title_similarity(name, c.get("title", ""))
        if score > best_score:
            best, best_score = c, score
    if best is None or best_score < 0.45:
        return None
    return best
