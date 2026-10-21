"""Общие функции «Истоков»: HTTP, OpenAlex, КиберЛенинка, рабочая папка.

Ключ OpenAlex берётся из OPENALEX_API_KEY. Без ключа запросы делят общий бесплатный
лимит на IP (в 2026 — около 1000 запросов в сутки), поэтому скрипты экономят запросы:
пакеты по 50 работ, только нужные поля.
"""
import datetime, html, json, math, os, pathlib, re, sys, time

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

OA = "https://api.openalex.org"
TIMEOUT = 40
FIELDS = ("id,doi,title,publication_year,authorships,primary_location,best_oa_location,"
          "locations,open_access,cited_by_count,referenced_works,abstract_inverted_index,"
          "keywords,language,type")


def log(*a):
    print(*a, file=sys.stderr)


def get(url, tries=4, impersonate="chrome", **kw):
    from curl_cffi import requests   # здесь, а не наверху: check_claims/speak работают и без curl_cffi
    for attempt in range(tries):
        try:
            r = requests.get(url, impersonate=impersonate, timeout=TIMEOUT, **kw)
        except Exception as e:
            log(f"  сеть: {str(e)[:120]}")
            time.sleep(2 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        return r
    return None


def post(url, **kw):
    from curl_cffi import requests
    return requests.post(url, impersonate="chrome", timeout=TIMEOUT, **kw)


def oa_get(path, params=None):
    """Запрос к OpenAlex. Возвращает JSON или None. Предупреждает, когда лимит на исходе."""
    p = dict(params or {})
    if os.environ.get("OPENALEX_API_KEY"):
        p["api_key"] = os.environ["OPENALEX_API_KEY"]
    if os.environ.get("OPENALEX_MAILTO"):
        p["mailto"] = os.environ["OPENALEX_MAILTO"]
    r = get(f"{OA}{path}", params=p)
    if r is None:
        return None
    left = r.headers.get("X-RateLimit-Remaining")
    if left and left.isdigit() and int(left) < 100:
        log(f"  OpenAlex: осталось {left} запросов на сегодня")
    if r.status_code != 200:
        log(f"  OpenAlex {r.status_code}: {r.text[:200]}")
        return None
    return r.json()


def short_id(x):
    return (x or "").rsplit("/", 1)[-1]


def abstract_text(inv):
    if not inv:
        return ""
    pos = sorted((p, w) for w, ps in inv.items() for p in ps)
    return " ".join(w for _, w in pos)


def brief(w):
    """Работа OpenAlex → компактная запись для карты, кандидатов и скачивания."""
    names = [a["author"]["display_name"] for a in w.get("authorships") or [] if a.get("author")]
    src = ((w.get("primary_location") or {}).get("source") or {})
    pdfs, pages = [], []
    for loc in [w.get("best_oa_location")] + (w.get("locations") or []):
        if not loc or not loc.get("is_oa"):
            continue                       # скачиваем только из открытых локаций
        for key, bucket in (("pdf_url", pdfs), ("landing_page_url", pages)):
            u = loc.get(key)
            if u and u not in bucket:
                bucket.append(u)
    best = w.get("best_oa_location") or {}
    return {
        "id": short_id(w.get("id")),
        "title": w.get("title") or "",
        "year": w.get("publication_year"),
        "authors": names,
        "venue": src.get("display_name") or "",
        "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
        "cited_by": w.get("cited_by_count") or 0,
        "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
        "license": best.get("license") or "",
        "pdf_urls": pdfs,
        "oa_pages": pages,
        "abstract": abstract_text(w.get("abstract_inverted_index")),
        "lang": w.get("language") or "",
        "type": w.get("type") or "",
        "refs": [short_id(x) for x in w.get("referenced_works") or []],
        "keywords": [k.get("display_name") for k in w.get("keywords") or [] if k.get("display_name")],
        "via": "openalex",
    }


def works_by_ids(ids):
    """Метаданные работ пакетами по 50 (один запрос на пакет)."""
    out = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for k in range(0, len(ids), 50):
        chunk = ids[k:k + 50]
        j = oa_get("/works", {"filter": "openalex_id:" + "|".join(chunk), "per-page": 50, "select": FIELDS})
        for w in (j or {}).get("results", []):
            b = brief(w)
            out[b["id"]] = b
    return out


def clean_title(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", s or "")).split())


def cyberleninka_search(q, n=20):
    try:
        r = post("https://cyberleninka.ru/api/search", json={"mode": "articles", "q": q, "size": n, "from": 0})
    except Exception as e:
        log(f"  КиберЛенинка: {e}")
        return []
    if r.status_code != 200:
        log(f"  КиберЛенинка {r.status_code}")
        return []
    out = []
    for a in r.json().get("articles", []):
        url = "https://cyberleninka.ru" + a.get("link", "")
        out.append({
            "id": "CL" + re.sub(r"\W", "", url.rsplit("/", 1)[-1])[-40:],
            "title": clean_title(a.get("name", "")),
            "year": a.get("year"),
            "authors": a.get("authors") or [],
            "venue": a.get("journal") or "",
            "doi": "", "cited_by": None, "is_oa": True, "license": "",
            "pdf_urls": [url + "/pdf"], "oa_pages": [url],
            "abstract": clean_title(a.get("annotation", "")),
            "lang": "ru", "type": "article", "refs": [], "keywords": [],
            "via": "cyberleninka",
        })
    return out


def norm(s):
    s = (s or "").lower().replace("ё", "е")
    return " ".join(re.sub(r"[^\w\s]", " ", s).split())


def term_hits(item, terms):
    text = norm(item.get("title", "") + " " + item.get("abstract", ""))
    return [t for t in terms if norm(t) and norm(t) in text]


def first_family(item):
    a = (item.get("authors") or ["anon"])[0]
    parts = a.replace(",", " ").split()
    if not parts:
        return "anon"
    # КиберЛенинка: «Фамилия Имя Отчество»; OpenAlex: «Имя Фамилия»
    fam = parts[0] if item.get("via") == "cyberleninka" else parts[-1]
    return re.sub(r"[^\w]", "", fam)[:20] or "anon"


def source_key(item):
    return f"{first_family(item)}{item.get('year') or ''}_{item['id']}"


def is_cyr(s):
    return bool(re.search(r"[а-яё]", (s or "").lower()))


def score_cited(n):
    return math.log10(1 + (n or 0))


def today():
    return datetime.date.today().isoformat()


def load(path, default=None):
    p = pathlib.Path(path)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save(path, data):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def authors_short(item, n=2):
    a = item.get("authors") or []
    s = ", ".join(a[:n])
    return s + (" и др." if len(a) > n else "")
