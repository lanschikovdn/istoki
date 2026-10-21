"""HTML-страница с выписками по каждому тезису.

    python build_page.py --dir <папка> [--out index.html]

Перед сборкой заново проверяет claims.json (check_claims.verify) — готовому
claims.checked.json не верит. На страницу идут только прошедшие тезисы; не прошедшие —
отдельным свёрнутым списком с причиной. Страница самодостаточная, открывается из папки:
ссылки на источники ведут в sources/<ключ>.md.
"""
import argparse, collections, html, pathlib

from common import load, today
from check_claims import verify

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--out", default="index.html")
a = ap.parse_args()
d = pathlib.Path(a.dir)

claims, _, _ = verify(d)
index = load(d / "sources" / "index.json", {})
m = load(d / "map.json", {})
E = html.escape
KIND = {"fact": "факт", "opinion": "мнение", "definition": "определение", "method": "методика", "contradiction": "противоречие"}


def who(key):
    s = index.get(key, {})
    au = s.get("authors") or []
    fam = [a.split()[0 if s.get("via") == "cyberleninka" else -1] for a in au[:2] if a.split()]
    name = (fam[0] if len(au) == 1 else f"{fam[0]}, {fam[1]}" if len(au) == 2 else f"{fam[0]} и др.") if fam else key
    return f"{name}, {s.get('year') or 'б. г.'}"


def evidence(e):
    span = f"{e['line']}–{e['line_end']}" if e.get("line_end", e["line"]) != e["line"] else f"{e['line']}"
    tag = ' <span class="tag">аннотация</span>' if e.get("source_status") == "только аннотация" else ""
    ctx = e.get("context") or {}
    rows = []
    for n, ln in enumerate(ctx.get("lines", []), ctx.get("from", 1)):
        hit = e["line"] <= n <= e.get("line_end", e["line"])
        rows.append(f'<div class="ln{" hit" if hit else ""}"><b>{n}</b>{E(ln)}</div>')
    return (f'<figure><blockquote>{E(e["quote"])}</blockquote>'
            f'<figcaption>{E(who(e["source"]))} · <a href="sources/{E(e["source"])}.md">sources/{E(e["source"])}.md:{span}</a>{tag}</figcaption>'
            f'<details><summary>контекст</summary><div class="ctx">{"".join(rows)}</div></details></figure>')


sections, failed, contra, count = [], [], [], collections.Counter()
for sec in claims.get("sections", []):
    cards = []
    for c in sec.get("claims", []):
        if not c.get("ok"):
            failed.append(c)
            continue
        count[c["kind"]] += 1
        if c["kind"] == "contradiction":
            contra.append(c)
        cards.append(f'<article class="claim" id="{E(c["id"])}" data-kind="{E(c["kind"])}">'
                     f'<header><span class="kind k-{E(c["kind"])}">{KIND[c["kind"]]}</span><span class="cid">{E(c["id"])}</span></header>'
                     f'<p class="thesis">{E(c["thesis"])}</p>{"".join(evidence(e) for e in c["evidence"])}</article>')
    if cards:
        sections.append((sec["title"], cards))

has_contra_sec = any(t.strip().lower() == "противоречия" for t, _ in sections)
nav = "".join(f'<a href="#s{i}">{E(t)}</a>' for i, (t, _) in enumerate(sections))
if not has_contra_sec:
    nav += '<a href="#contra">Противоречия</a>'
body = "".join(f'<section id="s{i}"><h2>{E(t)}</h2>{"".join(cs)}</section>' for i, (t, cs) in enumerate(sections))
contra_html = "".join(f'<li><a href="#{E(c["id"])}">{E(c["id"])}</a> — {E(c["thesis"])}</li>' for c in contra) or "<li>Не найдено.</li>"
chips = "".join(f'<button data-k="{k}" aria-pressed="true">{v} · {count[k]}</button>' for k, v in KIND.items() if count[k])

def ranked(bucket, n):
    rows = sorted((m.get(bucket) or {}).values(), key=lambda e: -sum(e["by_query"].values()))[:n]
    return ", ".join("%s (%d)" % (E(e["name"]), sum(e["by_query"].values())) for e in rows) or "—"


def src_row(key, v):
    link = '<a href="%s">ссылка</a>' % E(v["url"]) if v.get("url") else "—"
    cells = [E(", ".join(v.get("authors", [])[:3])), E(str(v.get("year") or "")), E(v.get("title", "")),
             E(v.get("status", "")), E(v.get("license") or "—"), link]
    return '<tr><td><a href="sources/%s.md">%s</a></td>' % (E(key), E(key)) + "".join("<td>%s</td>" % x for x in cells) + "</tr>"


def fail_item(c):
    why = c.get("errors", []) + ["%s:%s — %s" % (e.get("source"), e.get("line"), e.get("error"))
                                 for e in c.get("evidence", []) if not e.get("ok")]
    return '<li><b>%s</b> %s<br><span class="muted">%s</span></li>' % (E(c.get("id", "")), E(c.get("thesis", "")), E("; ".join(why)))


kw = collections.Counter(k for w in (m.get("works") or {}).values() for k in w.get("keywords", []))
qlog = "".join("<li>%s — %s</li>" % (E(x["date"]), E(x["q"])) for x in m.get("log", []))
maps = (f'<h3>Ключевые авторы</h3><p>{ranked("authors", 12)}</p>'
        f'<h3>Площадки</h3><p>{ranked("venues", 10)}</p>'
        f'<h3>Термины</h3><p>{", ".join("%s (%d)" % (E(k), n) for k, n in kw.most_common(25)) or "—"}</p>'
        f'<h3>Журнал запросов</h3><ul>{qlog}</ul>'
        '<p class="muted">Подробно — map.md. Числа в скобках — число работ в выдаче OpenAlex.</p>')
src_rows = "".join(src_row(k, v) for k, v in sorted(index.items()))
fail_html = "".join(fail_item(c) for c in failed)

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Истоки: выписки</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--card:#fff;--accent:#2f5d8a;--hit:#fff3c4;
--k-fact:#2f6f4e;--k-opinion:#8a5a2f;--k-definition:#4b4f9a;--k-method:#2f5d8a;--k-contradiction:#a33a3a}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ebe9e3;--muted:#a19f97;--line:#33322e;--card:#1f1f1c;--accent:#8fb6dd;--hit:#4a4222;
--k-fact:#7fc49f;--k-opinion:#d9a873;--k-definition:#a9adf0;--k-method:#8fb6dd;--k-contradiction:#ef8f8f}}}}
:root[data-theme="dark"]{{--bg:#161614;--fg:#ebe9e3;--muted:#a19f97;--line:#33322e;--card:#1f1f1c;--accent:#8fb6dd;--hit:#4a4222}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:880px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:1.6rem;line-height:1.25;margin:.2em 0}}h2{{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.3em}}
a{{color:var(--accent)}}.muted{{color:var(--muted);font-size:.9rem}}nav{{display:flex;flex-wrap:wrap;gap:6px 14px;margin:14px 0}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}}.chips button{{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:99px;padding:3px 12px;cursor:pointer;font:inherit;font-size:.85rem}}
.chips button[aria-pressed="false"]{{opacity:.4}}.claim{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}}
.claim header{{display:flex;justify-content:space-between;font-size:.8rem}}.kind{{font-weight:600;text-transform:uppercase;letter-spacing:.04em}}
.k-fact{{color:var(--k-fact)}}.k-opinion{{color:var(--k-opinion)}}.k-definition{{color:var(--k-definition)}}.k-method{{color:var(--k-method)}}.k-contradiction{{color:var(--k-contradiction)}}
.cid{{color:var(--muted)}}.thesis{{font-weight:600;margin:.4em 0 .6em}}figure{{margin:10px 0 0;padding-left:12px;border-left:3px solid var(--line)}}
blockquote{{margin:0;font-family:Georgia,serif}}figcaption{{font-size:.85rem;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}}
.tag{{border:1px solid var(--line);border-radius:4px;padding:0 5px;font-size:.75rem}}details summary{{cursor:pointer;font-size:.8rem;color:var(--muted)}}
.ctx{{font:12px/1.5 ui-monospace,Consolas,monospace;background:var(--bg);border-radius:6px;padding:6px;overflow-x:auto}}.ln{{white-space:pre-wrap}}.ln b{{display:inline-block;width:3.2em;color:var(--muted);font-weight:400}}.hit{{background:var(--hit)}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}td,th{{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}}.tw{{overflow-x:auto}}
</style></head><body><main>
<p class="muted">Истоки · {today()}</p><h1>{E(claims.get("question", ""))}</h1>
<p class="muted">Тезисов прошло проверку: {sum(count.values())}; не прошло: {len(failed)}. Источников: {len(index)}.
Каждый тезис — подпись к дословной цитате; цитата сверена со строкой файла скриптом check_claims.py.</p>
<nav>{nav}<a href="#map">Карта темы</a><a href="#src">Источники</a></nav>
<div class="chips" role="group" aria-label="Фильтр по виду">{chips}</div>
{body}
{'' if has_contra_sec else '<h2 id="contra">Противоречия</h2><ul>' + contra_html + '</ul>'}
<h2 id="map">Карта темы</h2>{maps}
<h2 id="src">Источники</h2><div class="tw"><table><tr><th>Файл</th><th>Авторы</th><th>Год</th><th>Название</th><th>Статус</th><th>Лицензия</th><th>Оригинал</th></tr>{src_rows}</table></div>
{f'<h2>Не прошли проверку</h2><details><summary>{len(failed)} тезисов</summary><ul>{fail_html}</ul></details>' if failed else ''}
</main><script>
document.querySelectorAll('.chips button').forEach(b=>b.onclick=()=>{{const on=b.getAttribute('aria-pressed')!=='true';
b.setAttribute('aria-pressed',on);document.querySelectorAll('.claim[data-kind="'+b.dataset.k+'"]').forEach(c=>c.hidden=!on)}});
</script></body></html>"""
(d / a.out).write_text(page, encoding="utf-8")
print(f"{a.out}: тезисов {sum(count.values())}, не прошли {len(failed)}")
