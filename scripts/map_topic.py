"""Карта темы: термины, ключевые авторы, площадки, ядро самых цитируемых работ.

    python map_topic.py --dir <папка> --question "вопрос" --q "english query" --q "русский запрос" [--from-year 2000] [--n 50]

Повторный запуск с новыми --q дополняет карту (тактика Бейтс: запрос меняется по ходу).
Пишет <папка>/map.json и черновик <папка>/map.md. Раздел «Фокус» в map.md не перезаписывается.
Расход OpenAlex: 3 запроса на каждый --q (выдача + группировки по авторам и журналам).
"""
import argparse, collections, pathlib, re

from common import (oa_get, brief, FIELDS, cyberleninka_search, is_cyr, load, save, today,
                    authors_short, score_cited, log)

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--question", default="")
ap.add_argument("--q", action="append", required=True, help="запрос; можно несколько")
ap.add_argument("--from-year", type=int)
ap.add_argument("--n", type=int, default=50, help="работ на запрос из OpenAlex (до 200)")
a = ap.parse_args()

d = pathlib.Path(a.dir)
m = load(d / "map.json", {"question": "", "log": [], "works": {}, "authors": {}, "venues": {}, "cyberleninka": {}})
if a.question:
    m["question"] = a.question

flt = f"from_publication_date:{a.from_year}-01-01" if a.from_year else None
for q in a.q:
    log(f"запрос: {q}")
    # поиск по названию и аннотации: полнотекстовый search даёт десятки тысяч случайных совпадений
    base = {"filter": f"title_and_abstract.search:{q}" + (f",{flt}" if flt else "")}
    j = oa_get("/works", {**base, "per-page": min(a.n, 200), "select": FIELDS, "sort": "relevance_score:desc"})
    res = (j or {}).get("results", [])
    total = (j or {}).get("meta", {}).get("count")
    for w in res:
        b = brief(w)
        prev = m["works"].get(b["id"])
        b["queries"] = sorted(set((prev or {}).get("queries", [])) | {q})
        m["works"][b["id"]] = b
    for field, bucket in (("authorships.author.id", "authors"), ("primary_location.source.id", "venues")):
        g = oa_get("/works", {**base, "group_by": field})
        for row in (g or {}).get("group_by", [])[:25]:
            key = row["key"].rsplit("/", 1)[-1]
            if key in ("unknown", "null") or not row.get("key_display_name"):
                continue
            e = m[bucket].setdefault(key, {"name": row["key_display_name"], "by_query": {}})
            e["by_query"][q] = row["count"]
    entry = {"date": today(), "q": q, "openalex_total": total, "taken": len(res)}
    if is_cyr(q):
        cl = cyberleninka_search(q, 20)
        for b in cl:
            prev = m["cyberleninka"].get(b["id"])
            b["queries"] = sorted(set((prev or {}).get("queries", [])) | {q})
            m["cyberleninka"][b["id"]] = b
        entry["cyberleninka"] = len(cl)
    m["log"].append(entry)

save(d / "map.json", m)

# ---------- map.md ----------
works = list(m["works"].values())
kw = collections.Counter(k for w in works for k in w["keywords"])
authors = sorted(m["authors"].items(), key=lambda kv: -sum(kv[1]["by_query"].values()))
venues = sorted(m["venues"].items(), key=lambda kv: -sum(kv[1]["by_query"].values()))
core = sorted(works, key=lambda w: (-len(w.get("queries", [])), -score_cited(w["cited_by"])))[:25]
core = sorted(core, key=lambda w: -w["cited_by"])

L = [f"# Карта темы: {m['question']}", "",
     f"_Черновик от {today()}. Собрано `map_topic.py` из OpenAlex и КиберЛенинки. "
     "Числа — из баз, не из памяти модели. Работ в карте: "
     f"{len(works)} (OpenAlex) + {len(m['cyberleninka'])} (КиберЛенинка)._", "",
     "## Журнал запросов", "", "| Дата | Запрос | Всего в OpenAlex | Взято | КиберЛенинка |", "|---|---|---|---|---|"]
for e in m["log"]:
    L.append(f"| {e['date']} | {e['q']} | {e.get('openalex_total', '')} | {e.get('taken', '')} | {e.get('cyberleninka', '')} |")
L += ["", "## Термины", "", "Ключевые слова OpenAlex у работ карты (слово — в скольких работах):", ""]
L += [", ".join(f"{k} ({n})" for k, n in kw.most_common(30)) or "—", ""]
L += ["## Ключевые авторы", "", "Число работ автора в выдаче по каждому запросу (OpenAlex):", "",
      "| Автор | OpenAlex ID | Работ |", "|---|---|---|"]
for key, e in authors[:15]:
    L.append(f"| {e['name']} | {key} | {sum(e['by_query'].values())} |")
L += ["", "## Площадки", "", "| Журнал / площадка | OpenAlex ID | Работ |", "|---|---|---|"]
for key, e in venues[:12]:
    L.append(f"| {e['name']} | {key} | {sum(e['by_query'].values())} |")
L += ["", "## Кандидаты в ядро", "",
      "Работы, найденные несколькими запросами, затем самые цитируемые. OA — есть открытый текст.", "",
      "| ID | Год | Авторы | Название | Цит. | OA |", "|---|---|---|---|---|---|"]
for w in core:
    L.append(f"| {w['id']} | {w['year']} | {authors_short(w)} | {w['title'][:110]} | {w['cited_by']} | {'да' if w['pdf_urls'] or w['oa_pages'] else '—'} |")
if m["cyberleninka"]:
    L += ["", "## Русскоязычные работы (КиберЛенинка, открытый доступ)", "",
          "| ID | Год | Авторы | Название | Журнал |", "|---|---|---|---|---|"]
    for w in sorted(m["cyberleninka"].values(), key=lambda w: -(w["year"] or 0))[:30]:
        L.append(f"| {w['id']} | {w['year']} | {authors_short(w)} | {w['title'][:110]} | {w['venue']} |")

old = (d / "map.md").read_text(encoding="utf-8") if (d / "map.md").exists() else ""
focus = re.search(r"\n## Фокус\n.*", old, re.S)
L += ["", focus.group(0).strip() if focus else
      "## Фокус\n\n_Заполняется после разговора с пользователем (точка Култау): фокус его словами, ядро — ID работ._"]
(d / "map.md").write_text("\n".join(L) + "\n", encoding="utf-8")
print(f"map.md: {len(works)} работ OpenAlex, {len(m['cyberleninka'])} КиберЛенинка, "
      f"{len(m['authors'])} авторов, {len(m['venues'])} площадок")
