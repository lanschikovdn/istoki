"""Скачивание первоисточников (только открытый доступ) и перевод в текст с номерами строк.

    python fetch.py --dir <папка> --ids W123 W456 CLxxxx ...
    python fetch.py --dir <папка> --top 20            # первые N кандидатов из candidates.json с терминами

Откуда берётся PDF: OA-локации OpenAlex (pdf_url, затем citation_pdf_url на открытой странице),
для КиберЛенинки — ссылка /pdf. Платные страницы не трогаем.
Результат: sources/<ключ>.md (текст с метками [стр. N]), sources/pdf/<ключ>.pdf, sources/index.json.
Нет PDF — файл с аннотацией и статусом «только аннотация».
Готовый .md не перезаписывается: на его строки уже могут ссылаться выписки. --force — только если выписок ещё нет.
"""
import argparse, difflib, pathlib, re, sys, time

import fitz  # PyMuPDF

from common import get, load, save, works_by_ids, source_key, today, log
from check_claims import canon, sha

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--ids", nargs="*", default=[])
ap.add_argument("--top", type=int, default=0)
ap.add_argument("--force", action="store_true")
ap.add_argument("--confirm", nargs="+", metavar="KEY", help="подтвердить источник со статусом ПРОВЕРИТЬ после проверки глазами")
a = ap.parse_args()

d = pathlib.Path(a.dir)
src = d / "sources"
(src / "pdf").mkdir(parents=True, exist_ok=True)
index = load(src / "index.json", {})

if a.confirm:
    for key in a.confirm:
        meta, md = index.get(key), src / f"{key}.md"
        if not meta or not md.exists() or "ПРОВЕРИТЬ" not in meta["status"]:
            print(f"{key}: нечего подтверждать")
            continue
        meta["status"] = "полный текст (подтверждено вручную)"
        text = md.read_text(encoding="utf-8").splitlines()
        text = [f"- Статус: {meta['status']}; подтверждено {today()}" if ln.startswith("- Статус:") else ln for ln in text]
        md.write_text("\n".join(text) + "\n", encoding="utf-8")   # число строк не меняется
        meta["sha256"] = sha(md)
        print(f"{key}: подтверждён")
    save(src / "index.json", index)
    sys.exit(0)

known = {}
m = load(d / "map.json", {})
known.update(m.get("works", {}))
known.update(m.get("cyberleninka", {}))
c = load(d / "candidates.json", {})
known.update(c.get("core", {}))
known.update(c.get("candidates", {}))

ids = list(a.ids)
if a.top:
    ranked = sorted((b for b in c.get("candidates", {}).values() if b.get("term_hits")), key=lambda b: -b["score"])
    ids += [b["id"] for b in ranked[:a.top]]
need = [i for i in ids if i not in known and not i.startswith("CL")]
if need:
    known.update(works_by_ids(need))


def pdf_candidates(item):
    urls = list(item.get("pdf_urls") or [])
    # PubMed Central отдаёт ботам страницу-проверку; официальная выдача PDF того же архива — Europe PMC
    for u in urls + list(item.get("oa_pages") or []):
        m = re.search(r"(?:PMC|pmc/articles/)(\d{5,})", u)
        if m:
            urls.append(f"https://europepmc.org/articles/PMC{m.group(1)}?pdf=render")
            break
    for page in item.get("oa_pages") or []:
        if "doaj.org" in page or "ncbi.nlm.nih.gov" in page:
            continue
        r = get(page, tries=1)
        if r is None or r.status_code != 200:
            continue
        if r.content[:4] == b"%PDF":
            return urls + [page]
        mt = re.search(r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)', r.text, re.I) \
            or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url', r.text, re.I)
        if mt and mt.group(1) not in urls:
            urls.append(mt.group(1))
    return urls


def download(urls):
    # разные издатели по-разному отвечают разным стандартным клиентам: по одной попытке на профиль.
    # 403 и страницы-проверки не обходим.
    for u in dict.fromkeys(urls):
        for prof in ("chrome", "safari", None):
            r = get(u, tries=1, impersonate=prof)
            if r is None:
                continue
            if r.status_code == 200 and r.content[:4] == b"%PDF" and len(r.content) < 60_000_000:
                return u, r.content
            if r.status_code in (401, 403, 404, 410):
                break
        time.sleep(1)
    return None, None


def header(item, key, status, url):
    return [f"<!-- istoki source: {key} -->", f"# {item['title']}", "",
            f"- Авторы: {', '.join(item.get('authors') or []) or '—'}",
            f"- Год: {item.get('year') or '—'}; издание: {item.get('venue') or '—'}",
            f"- DOI: {item.get('doi') or '—'}; ID: {item['id']}",
            f"- Источник текста: {url or '—'}",
            f"- Лицензия: {item.get('license') or 'не указана'}",
            f"- Статус: {status}; получено {today()}", "", "---", ""]


for i in dict.fromkeys(ids):
    item = known.get(i)
    if not item:
        log(f"{i}: нет метаданных, пропуск")
        continue
    key = source_key(item)
    md = src / f"{key}.md"
    if md.exists() and not a.force:
        log(f"{key}: уже есть")
        continue
    log(f"{key}: ищу текст…")
    url, pdf = download(pdf_candidates(item))
    lines, status = [], ""
    pages = None
    if pdf:
        (src / "pdf" / f"{key}.pdf").write_bytes(pdf)
        try:
            doc = fitz.open(stream=pdf, filetype="pdf")
            pages = [[ln.rstrip() for ln in page.get_text("text").splitlines() if ln.strip()] for page in doc]
        except Exception as e:
            log(f"  PDF не читается: {e}")
    if pages is not None:
        for n, pg in enumerate(pages, 1):
            lines.append(f"[стр. {n}]")
            lines += pg
        body = sum(len(ln) for pg in pages for ln in pg)
        # та ли это работа: самый длинный общий кусок названия на первых двух страницах
        tk = canon(item["title"])
        fk = canon(" ".join(ln for pg in pages[:2] for ln in pg))
        mt = difflib.SequenceMatcher(None, fk, tk, autojunk=False).find_longest_match(0, len(fk), 0, len(tk))
        found = mt.size / max(len(tk), 1)
        if body < 1500:
            status = "PDF без текстового слоя (скан) — цитировать нельзя"
        elif found < 0.6:
            status = (f"полный текст, ПРОВЕРИТЬ: название совпало на {found:.0%}. Открой файл; если работа та — "
                      f"fetch.py --confirm {key}, если нет — удали файл и запись")
        else:
            status = f"полный текст (PDF, {len(pages)} стр.)"
    elif pdf:
        status = "PDF не читается — цитировать нельзя"
    elif item.get("abstract"):
        status = "только аннотация"
        lines = ["[аннотация]"] + re.split(r"(?<=[.!?])\s+", item["abstract"])
        url = (item.get("oa_pages") or [""])[0] or (f"https://doi.org/{item['doi']}" if item.get("doi") else "")
    else:
        status = "текст не получен"
    md.write_text("\n".join(header(item, key, status, url) + lines) + "\n", encoding="utf-8")
    index[key] = {"id": item["id"], "title": item["title"], "authors": item.get("authors") or [],
                  "year": item.get("year"), "venue": item.get("venue"), "doi": item.get("doi"),
                  "url": url, "license": item.get("license"), "status": status, "via": item.get("via"),
                  "lines": len(header(item, key, status, url)) + len(lines), "sha256": sha(md)}
    save(src / "index.json", index)
    print(f"{key}: {status}")
    time.sleep(1)

full = sum(1 for v in index.values() if v["status"].startswith("полный текст"))
print(f"sources/: {len(index)} файлов, полный текст: {full}, только аннотация: "
      f"{sum(1 for v in index.values() if v['status'] == 'только аннотация')}")
