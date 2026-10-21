"""Цепочки (Эллис: chaining): ссылки назад и цитирования вперёд от ядра.

    python chain.py --dir <папка> --core W1 W2 ... --terms "burnout" "выгорание" [--forward 25] [--max-back 300] [--from-year 2010]

Ядро — ID работ OpenAlex, которые пользователь выбрал на точке фокуса.
Ранг кандидата: сколько работ ядра на него ссылается (×2) + совпадения терминов
в названии и аннотации + log10(цитирований). Работы без единого термина уходят в конец.
Пишет <папка>/candidates.json и <папка>/candidates.md.
Расход OpenAlex: 1 запрос на 50 работ ядра + 1 на 50 ссылок назад + 1 на каждую работу ядра (вперёд).
"""
import argparse, collections, pathlib

from common import oa_get, works_by_ids, brief, FIELDS, term_hits, score_cited, load, save, today, authors_short, log

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--core", nargs="+", required=True)
ap.add_argument("--terms", nargs="+", required=True, help="термины фокуса для ранжирования")
ap.add_argument("--forward", type=int, default=25, help="цитирующих работ на каждую работу ядра")
ap.add_argument("--max-back", type=int, default=300, help="сколько ссылок назад загружать (самые частые)")
ap.add_argument("--from-year", type=int, help="отсечка по году для цитирований вперёд")
ap.add_argument("--hops", type=int, default=1, choices=[1, 2],
                help="2 — ещё шаг назад от 30 лучших кандидатов (к более ранним первоисточникам)")
a = ap.parse_args()

d = pathlib.Path(a.dir)
core = works_by_ids(a.core)
missing = set(a.core) - set(core)
if missing:
    log(f"не найдены в OpenAlex: {', '.join(sorted(missing))}")

back = collections.Counter(r for w in core.values() for r in w["refs"])
for c in core:
    back.pop(c, None)
back_ids = [i for i, _ in back.most_common(a.max_back)]
log(f"ссылок назад: {len(back)} (загружаю {len(back_ids)})")
cand = works_by_ids(back_ids)
paths = collections.defaultdict(list)
for i in back_ids:
    paths[i].append(f"назад ×{back[i]}")

for cid in core:
    flt = f"cites:{cid}" + (f",from_publication_date:{a.from_year}-01-01" if a.from_year else "")
    j = oa_get("/works", {"filter": flt, "sort": "cited_by_count:desc", "per-page": a.forward, "select": FIELDS})
    for w in (j or {}).get("results", []):
        b = brief(w)
        if b["id"] in core:
            continue
        cand.setdefault(b["id"], b)
        paths[b["id"]].append(f"вперёд от {cid}")

def rank():
    rows = []
    for i, b in cand.items():
        hits = term_hits(b, a.terms)
        b["chain"] = paths[i]
        b["term_hits"] = hits
        b["score"] = round(2 * (back.get(i, 0) + back2.get(i, 0) / 2) + len(hits) + score_cited(b["cited_by"])
                           - (0 if hits else 10), 2)
        rows.append(b)
    return sorted(rows, key=lambda b: -b["score"])


back2 = collections.Counter()
rows = rank()
if a.hops == 2:
    # Эллис: chaining до первоисточников — ссылки самых сильных кандидатов (refs уже загружены)
    top = [b for b in rows if b["term_hits"]][:30]
    back2 = collections.Counter(r for b in top for r in b["refs"])
    for i in list(back2):
        if i in core or i in cand or back2[i] < 2:
            back2.pop(i)
    ids2 = [i for i, _ in back2.most_common(a.max_back)]
    log(f"второй шаг назад: {len(ids2)} работ, на которые ссылаются ≥2 сильных кандидата")
    for i, b in works_by_ids(ids2).items():
        cand[i] = b
        paths[i].append(f"назад 2-й шаг ×{back2[i]}")
    rows = rank()

prev = load(d / "candidates.json", {"runs": [], "core": {}, "candidates": {}})
prev["runs"].append({"date": today(), "core": a.core, "terms": a.terms, "found": len(rows)})
prev["core"].update(core)
for b in rows:
    prev["candidates"][b["id"]] = b
save(d / "candidates.json", prev)

L = [f"# Кандидаты от ядра ({today()})", "",
     f"Ядро: {', '.join(a.core)}. Термины фокуса: {', '.join(a.terms)}.", "",
     "Ранг = 2 × (сколько работ ядра ссылаются) + совпадения терминов + log10(цитирований). "
     "Без терминов — штраф −10. OA — есть открытый текст.", "",
     "| # | ID | Год | Авторы | Название | Цит. | Путь | Термины | OA | Ранг |",
     "|---|---|---|---|---|---|---|---|---|---|"]
for n, b in enumerate(rows, 1):
    L.append(f"| {n} | {b['id']} | {b['year']} | {authors_short(b)} | {b['title'][:100]} | {b['cited_by']} | "
             f"{'; '.join(b['chain'][:3])} | {', '.join(b['term_hits'])} | {'да' if b['pdf_urls'] or b['oa_pages'] else '—'} | {b['score']} |")
(d / "candidates.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(f"candidates.md: {len(rows)} кандидатов, с терминами: {sum(1 for b in rows if b['term_hits'])}, "
      f"с открытым текстом: {sum(1 for b in rows if b['pdf_urls'] or b['oa_pages'])}")
