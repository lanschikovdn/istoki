"""HTML-страница с выписками: слои A (выписки), B (синтез), C (предложения ИИ).

    python build_page.py --dir <папка> [--out index.html]

Перед сборкой заново проверяет claims.json (check_claims.verify) — готовому
claims.checked.json не верит. Слой A — только допущенные тезисы: цитата сверена, рецензия
свежая, смысл supported, границы within_scope. У каждого тезиса статусы показаны раздельно,
без общего «проверено». Недопущенные тезисы, ошибки и журнал исключённых — отдельными
блоками ниже. Страница самодостаточная, ссылки на источники ведут в sources/<ключ>.md.
"""
import argparse, collections, html, pathlib

from common import load, today
from check_claims import verify, all_claims

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
SUPPORT_RU = {"supported": ("поддержан", "ok"), "partially_supported": ("частично", "warn"),
              "unsupported": ("не поддержан", "bad"), "not_reviewed": ("не проверен", "none")}
SCOPE_RU = {"within_scope": ("в пределах", "ok"), "overgeneralized": ("расширено", "bad"),
            "unclear": ("неясно", "warn"), "not_reviewed": ("не проверены", "none")}
SCOPE_KEYS_RU = {"sample": "выборка", "country": "страна", "language": "язык", "instrument": "методика",
                 "design": "дизайн", "outcomes": "показатели"}
CONTRA_RU = {"direct": "прямое противоречие", "different_conditions": "разные условия",
             "different_definitions": "разные определения", "insufficient_data": "мало данных для сопоставления"}


def who(key):
    s = index.get(key, {})
    au = s.get("authors") or []
    fam = [a.split()[0 if s.get("via") == "cyberleninka" else -1] for a in au[:2] if a.split()]
    name = (fam[0] if len(au) == 1 else f"{fam[0]}, {fam[1]}" if len(au) == 2 else f"{fam[0]} и др.") if fam else key
    return f"{name}, {s.get('year') or 'б. г.'}"


def evidence(e):
    span = f"{e['line']}–{e['line_end']}" if e.get("line_end", e["line"]) != e["line"] else f"{e['line']}"
    ctx = e.get("context") or {}
    rows = []
    for n, ln in enumerate(ctx.get("lines", []), ctx.get("from", 1)):
        hit = e["line"] <= n <= e.get("line_end", e["line"])
        rows.append(f'<div class="ln{" hit" if hit else ""}"><b>{n}</b>{E(ln)}</div>')
    return (f'<figure><blockquote>{E(e["quote"])}</blockquote>'
            f'<figcaption>{E(who(e["source"]))} · <a href="sources/{E(e["source"])}.md">sources/{E(e["source"])}.md:{span}</a></figcaption>'
            f'<details><summary>контекст</summary><div class="ctx">{"".join(rows)}</div></details></figure>')


def badge(label, value, cls):
    return f'<span class="st st-{cls}">{E(label)}: <b>{E(value)}</b></span>'


def statuses(c):
    rv, state = c.get("review") or {}, c.get("review_state")
    fresh = state == "fresh"
    sup = SUPPORT_RU.get(rv.get("support") if fresh else "not_reviewed", ("не проверен", "none"))
    sco = SCOPE_RU.get(rv.get("scope") if fresh else "not_reviewed", ("не проверены", "none"))
    abstract = any(e.get("source_status") == "только аннотация" for e in c["evidence"])
    mode = {"independent": ("независимая", "ok"), "self": ("самопроверка", "warn")}.get(rv.get("mode"), ("нет", "none"))
    if state == "stale":
        mode = ("устарела", "bad")
    return ('<div class="sts">' + badge("цитата", "сверена" if c["ok"] else "ошибка", "ok" if c["ok"] else "bad")
            + badge("смысл", *sup) + badge("границы", *sco)
            + badge("текст", "аннотация" if abstract else "полный", "warn" if abstract else "ok")
            + badge("рецензия", *mode) + "</div>")


def extras(c):
    out = []
    cf = c.get("cited_from")
    if cf:
        out.append(f'<p class="note">Вторичное утверждение: источник пересказывает позицию <b>{E(cf.get("original", ""))}</b>.'
                   f' {E(cf.get("note") or "Первоисточник не прочитан.")}</p>')
    sc = c.get("scope")
    if sc:
        cells = "".join(f"<dt>{E(SCOPE_KEYS_RU[k])}</dt><dd>{E(str(sc[k])) if sc[k] not in (None, '') else '<i>неизвестно</i>'}</dd>"
                        for k in SCOPE_KEYS_RU if k in sc)
        out.append(f'<dl class="scope">{cells}</dl>')
    cm = c.get("comparison")
    if cm:
        li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs or []) or "<li>—</li>"
        out.append(f'<div class="cmp"><p><b>Общий вопрос:</b> {E(cm.get("question", ""))}</p>'
                   f'<p><b>Тип расхождения:</b> {E(CONTRA_RU.get(cm.get("type"), cm.get("type") or "—"))}</p>'
                   f'<div class="cols"><div><b>Совпадает</b><ul>{li(cm.get("same"))}</ul></div>'
                   f'<div><b>Различается</b><ul>{li(cm.get("different"))}</ul></div></div>'
                   + (f'<p><b>Не решено:</b> {E(cm["open"])}</p>' if cm.get("open") else "") + '</div>')
    rv = c.get("review")
    if rv and (rv.get("note") or rv.get("problems")):
        probs = "".join(f"<li>{E(p)}</li>" for p in rv.get("problems") or [])
        out.append(f'<details><summary>рецензия от {E(rv.get("date", ""))}</summary><p>{E(rv.get("note", ""))}</p>'
                   f'{"<ul>" + probs + "</ul>" if probs else ""}</details>')
    return "".join(out)


def card(c, why=None):
    reasons = f'<p class="why">Не допущен: {E("; ".join(why))}</p>' if why else ""
    return (f'<article class="claim" id="{E(c["id"])}" data-kind="{E(c["kind"])}">'
            f'<header><span class="kind k-{E(c["kind"])}">{KIND.get(c["kind"], c["kind"])}</span><span class="cid">{E(c["id"])}</span></header>'
            f'<p class="thesis">{E(c["thesis"])}</p>{statuses(c)}{reasons}{extras(c)}'
            f'{"".join(evidence(e) for e in c["evidence"] if e.get("ok"))}</article>')


def refs(ids):
    return ", ".join(f'<a href="#{E(r)}">{E(r)}</a>' for r in ids)


sections, pending, failed, excluded, count = [], [], [], [], collections.Counter()
for sec in claims.get("sections", []):
    cards = []
    for c in sec.get("claims", []):
        if c.get("status") == "excluded":
            excluded.append(c)
        elif not c.get("ok"):
            failed.append(c)
        elif not c.get("admitted"):
            pending.append(c)
        else:
            count[c["kind"]] += 1
            cards.append(card(c))
    if cards:
        sections.append((sec["title"], cards))

synth = [s for s in claims.get("synthesis") or [] if s.get("ok")]
props = [p for p in claims.get("proposals") or [] if p.get("ok")]
bad_layers = [x for x in (claims.get("synthesis") or []) + (claims.get("proposals") or []) if not x.get("ok")]
synth_html = "".join(f'<article class="layer" id="{E(s["id"])}"><header><span class="kind">синтез</span><span class="cid">{E(s["id"])}</span></header>'
                     f'<p class="thesis">{E(s["text"])}</p><p class="muted">Опора: {refs(s["basis"])}</p>'
                     f'<p class="muted"><b>Ограничения:</b> {E(s["limits"])}</p></article>' for s in synth)
li = lambda xs: "".join(f"<li>{E(x)}</li>" for x in xs or [])
prop_html = "".join(f'<article class="layer prop" id="{E(p["id"])}"><header><span class="kind">предложение ИИ</span><span class="cid">{E(p["id"])}</span></header>'
                    f'<p class="thesis">{E(p["text"])}</p><p class="muted">Опора: {refs(p["basis"])}</p>'
                    + (f'<p><b>Допущения:</b></p><ul>{li(p.get("assumptions"))}</ul>' if p.get("assumptions") else "")
                    + f'<p><b>Что не проверялось:</b> {E(p["not_checked"])}</p><p><b>Как проверить пилотно:</b> {E(p["pilot"])}</p>'
                    + (f'<p><b>Риски и критерии остановки:</b> {E(p["risks"])}</p>' if p.get("risks") else "")
                    + '</article>' for p in props)

bad_html = "".join("<li><b>%s</b> %s</li>" % (E(x.get("id", "")), E("; ".join(x.get("errors", [])))) for x in bad_layers)
nav = "".join(f'<a href="#sec{i}">{E(t)}</a>' for i, (t, _) in enumerate(sections))   # sec…, не s…: s1 — синтез
nav += ('<a href="#layer-b">Синтез</a>' if synth else "") + ('<a href="#layer-c">Предложения</a>' if props else "")
nav += '<a href="#pending">Не допущены</a>' if pending else ""
body = "".join(f'<section id="sec{i}"><h2>{E(t)}</h2>{"".join(cs)}</section>' for i, (t, cs) in enumerate(sections)) \
    or '<p class="why">В основной слой не допущен ни один тезис: нет свежих рецензий или они не пропустили тезисы.</p>'
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


def excl_item(c):
    ex = c.get("exclusion") or {}
    att = f", попыток: {ex['attempts']}" if ex.get("attempts") else ""
    return (f'<li><b>{E(c["id"])}</b> {E(c.get("thesis", ""))}<br><span class="muted">'
            f'{E(ex.get("date", ""))}: {E(ex.get("reason", ""))}{E(att)}</span></li>')


kw = collections.Counter(k for w in (m.get("works") or {}).values() for k in w.get("keywords", []))
qlog = "".join("<li>%s — %s</li>" % (E(x["date"]), E(x["q"])) for x in m.get("log", []))
maps = (f'<h3>Ключевые авторы</h3><p>{ranked("authors", 12)}</p>'
        f'<h3>Площадки</h3><p>{ranked("venues", 10)}</p>'
        f'<h3>Термины</h3><p>{", ".join("%s (%d)" % (E(k), n) for k, n in kw.most_common(25)) or "—"}</p>'
        f'<h3>Журнал запросов</h3><ul>{qlog}</ul>'
        '<p class="muted">Подробно — map.md. Числа в скобках — число работ в выдаче OpenAlex.</p>')
src_rows = "".join(src_row(k, v) for k, v in sorted(index.items()))
active = [c for c in all_claims(claims) if c.get("status") != "excluded"]
full = sum(1 for v in index.values() if v.get("status", "").startswith("полный текст ("))
stats = (f'Тезисов: {len(active)}. Цитата сверена со строкой файла: {sum(1 for c in active if c["ok"])}. '
         f'Допущено в основной слой (смысл и границы подтверждены свежей рецензией): {sum(count.values())}. '
         f'Не допущено: {len(pending)}. Ошибки цитат: {len(failed)}. Исключено: {len(excluded)}. '
         f'Источников: {len(index)}, из них с полным текстом: {full}.')

page = f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Истоки: выписки</title><style>
:root{{--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6a65;--line:#e4e1d8;--card:#fff;--accent:#2f5d8a;--hit:#fff3c4;
--k-fact:#2f6f4e;--k-opinion:#8a5a2f;--k-definition:#4b4f9a;--k-method:#2f5d8a;--k-contradiction:#a33a3a;
--ok:#2f6f4e;--warn:#8a5a00;--bad:#a33a3a;--none:#6b6a65;--prop:#fff6e5}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{--bg:#161614;--fg:#ebe9e3;--muted:#a19f97;--line:#33322e;--card:#1f1f1c;--accent:#8fb6dd;--hit:#4a4222;
--k-fact:#7fc49f;--k-opinion:#d9a873;--k-definition:#a9adf0;--k-method:#8fb6dd;--k-contradiction:#ef8f8f;
--ok:#7fc49f;--warn:#e0b45a;--bad:#ef8f8f;--none:#a19f97;--prop:#2a2416}}}}
:root[data-theme="dark"]{{--bg:#161614;--fg:#ebe9e3;--muted:#a19f97;--line:#33322e;--card:#1f1f1c;--accent:#8fb6dd;--hit:#4a4222;
--ok:#7fc49f;--warn:#e0b45a;--bad:#ef8f8f;--none:#a19f97;--prop:#2a2416}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:880px;margin:0 auto;padding:24px 16px 64px}}h1{{font-size:1.6rem;line-height:1.25;margin:.2em 0}}h2{{margin-top:2.2em;border-bottom:1px solid var(--line);padding-bottom:.3em}}
a{{color:var(--accent)}}.muted{{color:var(--muted);font-size:.9rem}}nav{{display:flex;flex-wrap:wrap;gap:6px 14px;margin:14px 0}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}}.chips button{{border:1px solid var(--line);background:var(--card);color:var(--fg);border-radius:99px;padding:3px 12px;cursor:pointer;font:inherit;font-size:.85rem}}
.chips button[aria-pressed="false"]{{opacity:.4}}.claim,.layer{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}}
.prop{{background:var(--prop)}}.layer-head{{border:1px dashed var(--line);border-radius:8px;padding:8px 12px}}
.claim header,.layer header{{display:flex;justify-content:space-between;font-size:.8rem}}.kind{{font-weight:600;text-transform:uppercase;letter-spacing:.04em}}
.k-fact{{color:var(--k-fact)}}.k-opinion{{color:var(--k-opinion)}}.k-definition{{color:var(--k-definition)}}.k-method{{color:var(--k-method)}}.k-contradiction{{color:var(--k-contradiction)}}
.cid{{color:var(--muted)}}.thesis{{font-weight:600;margin:.4em 0 .6em}}figure{{margin:10px 0 0;padding-left:12px;border-left:3px solid var(--line)}}
.sts{{display:flex;flex-wrap:wrap;gap:4px 6px;margin:0 0 8px}}.st{{font-size:.75rem;border:1px solid currentColor;border-radius:4px;padding:0 6px}}
.st-ok{{color:var(--ok)}}.st-warn{{color:var(--warn)}}.st-bad{{color:var(--bad)}}.st-none{{color:var(--none);border-style:dashed}}
.why{{color:var(--bad);font-size:.9rem}}.note{{font-size:.9rem;border-left:3px solid var(--warn);padding-left:8px}}
.scope{{display:grid;grid-template-columns:max-content 1fr;gap:2px 10px;font-size:.85rem;margin:6px 0}}.scope dt{{color:var(--muted)}}.scope dd{{margin:0}}
.cmp{{font-size:.9rem;background:var(--bg);border-radius:8px;padding:8px 12px;margin:8px 0}}.cmp p{{margin:.3em 0}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
@media (max-width:560px){{.cols{{grid-template-columns:1fr}}}}
blockquote{{margin:0;font-family:Georgia,serif}}figcaption{{font-size:.85rem;color:var(--muted);margin-top:4px;overflow-wrap:anywhere}}
details summary{{cursor:pointer;font-size:.8rem;color:var(--muted)}}
.ctx{{font:12px/1.5 ui-monospace,Consolas,monospace;background:var(--bg);border-radius:6px;padding:6px;overflow-x:auto}}.ln{{white-space:pre-wrap}}.ln b{{display:inline-block;width:3.2em;color:var(--muted);font-weight:400}}.hit{{background:var(--hit)}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}td,th{{border-bottom:1px solid var(--line);padding:5px 6px;text-align:left;vertical-align:top}}.tw{{overflow-x:auto}}
</style></head><body><main>
<p class="muted">Истоки · {today()}</p><h1>{E(claims.get("question", ""))}</h1>
<p class="muted">{E(stats)} Совпадение цитаты не означает, что утверждение автора истинно; рецензент-модель может ошибаться.</p>
<nav>{nav}<a href="#map">Карта темы</a><a href="#src">Источники</a></nav>
<h2 class="layer-head">A. Выписки</h2>
<p class="muted">Подпись к дословной цитате. Здесь только допущенные тезисы.</p>
<div class="chips" role="group" aria-label="Фильтр по виду">{chips}</div>
{body}
{f'<h2 class="layer-head" id="layer-b">B. Синтез</h2><p class="muted">Сопоставление допущенных тезисов. Это не вывод авторов статей; каждое утверждение опирается на тезисы по ссылкам.</p>{synth_html}' if synth else ''}
{f'<h2 class="layer-head" id="layer-c">C. Предложения ИИ</h2><p class="why">Это предложения модели по применению, а не рекомендации авторов статей. У каждого — допущения и способ проверки.</p>{prop_html}' if props else ''}
{f'<h2 id="pending">Не допущены в основной слой</h2><details><summary>{len(pending)} тезисов: цитата верна, но рецензии нет, она устарела или не подтвердила смысл и границы</summary>{"".join(card(c, c.get("not_admitted")) for c in pending)}</details>' if pending else ''}
{f'<h2>Синтез и предложения с ошибками</h2><ul>{bad_html}</ul>' if bad_layers else ''}
<h2 id="map">Карта темы</h2>{maps}
<h2 id="src">Источники</h2><div class="tw"><table><tr><th>Файл</th><th>Авторы</th><th>Год</th><th>Название</th><th>Статус</th><th>Лицензия</th><th>Оригинал</th></tr>{src_rows}</table></div>
{f'<h2>Ошибки цитат</h2><details><summary>{len(failed)} тезисов</summary><ul>{"".join(fail_item(c) for c in failed)}</ul></details>' if failed else ''}
{f'<h2>Журнал исключённых тезисов</h2><details><summary>{len(excluded)} тезисов — в синтез и предложения не входят</summary><ul>{"".join(excl_item(c) for c in excluded)}</ul></details>' if excluded else ''}
</main><script>
document.querySelectorAll('.chips button').forEach(b=>b.onclick=()=>{{const on=b.getAttribute('aria-pressed')!=='true';
b.setAttribute('aria-pressed',on);document.querySelectorAll('section .claim[data-kind="'+b.dataset.k+'"]').forEach(c=>c.hidden=!on)}});
</script></body></html>"""
(d / a.out).write_text(page, encoding="utf-8")
print(f"{a.out}: допущено {sum(count.values())}, не допущено {len(pending)}, ошибки цитат {len(failed)}, "
      f"исключено {len(excluded)}, синтез {len(synth)}, предложения {len(props)}")
