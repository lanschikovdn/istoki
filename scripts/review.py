"""Содержательная рецензия тезисов: пакет для рецензента, запись решений, исключение тезиса.

    python review.py --dir D --packet [--ids c1 c2] [--context 12]
        → D/review_packet.json: тезисы без свежей рецензии (или --ids) с выписками, контекстом
          вокруг каждой цитаты и шапкой источника. Рецензент может читать файлы источника дальше.
    python review.py --dir D --apply reviews.json --mode independent|self
        → записывает решения в claims.json; каждой рецензии ставится хеш текущей версии тезиса.
          Изменится подпись или выписка — рецензия станет устаревшей (check_claims.py).
    python review.py --dir D --exclude c7 --reason "…" [--attempts 3]
        → тезис остаётся в claims.json со статусом excluded, причиной и датой; в выдачу не идёт.

Формат reviews.json: [{"id": "c1", "hash": "<из пакета>", "support": "supported", "scope": "within_scope",
  "note": "кратко почему", "problems": ["…"], "fix": "предложенная подпись"}]
hash рецензент копирует из пакета: так решение привязано к той версии тезиса, которую он видел.
Тезис изменился после --packet — --apply откажет, нужен новый пакет.
Рецензент не правит claims.json и источники сам — он выдаёт reviews.json.
"""
import argparse, pathlib, shutil, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import load, save, today
from check_claims import verify, all_claims, claim_hash, SUPPORT, SCOPE, MODES

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--packet", action="store_true")
g.add_argument("--apply", metavar="REVIEWS_JSON")
g.add_argument("--exclude", metavar="ID")
ap.add_argument("--ids", nargs="*")
ap.add_argument("--context", type=int, default=12, help="строк контекста до и после цитаты")
ap.add_argument("--mode", choices=sorted(MODES), help="independent — отдельный агент; self — повторная самопроверка")
ap.add_argument("--reason")
ap.add_argument("--attempts", type=int)
a = ap.parse_args()
d = pathlib.Path(a.dir)


def write_claims(raw):
    shutil.copyfile(d / "claims.json", d / "claims.json.bak")
    save(d / "claims.json", raw)


if a.packet:
    checked, _, _ = verify(d)
    index = load(d / "sources" / "index.json", {})
    out = []
    for c in all_claims(checked):
        if c.get("status", "active") == "excluded" or not c.get("ok"):
            continue
        if a.ids and c["id"] not in a.ids:
            continue
        if not a.ids and c["review_state"] == "fresh":
            continue
        ev = []
        for e in c["evidence"]:
            lines = (d / "sources" / f"{e['source']}.md").read_text(encoding="utf-8").splitlines()
            lo, hi = max(1, e["line"] - a.context), min(len(lines), e.get("line_end", e["line"]) + a.context)
            meta = index.get(e["source"], {})
            ev.append({"source": e["source"], "line": e["line"], "line_end": e.get("line_end", e["line"]),
                       "quote": e["quote"], "source_status": meta.get("status"),
                       "source_title": meta.get("title"), "source_authors": meta.get("authors"),
                       "source_header": lines[:10],
                       "context": [f"{n}: {lines[n - 1]}" for n in range(lo, hi + 1)]})
        out.append({k: c.get(k) for k in ("id", "kind", "thesis", "cited_from", "scope", "comparison")}
                   | {"hash": claim_hash(c), "evidence": ev})
    save(d / "review_packet.json", {
        "instructions": ("Для каждого тезиса реши: support — " + " / ".join(sorted(SUPPORT)) +
                         "; scope — " + " / ".join(sorted(SCOPE)) + ". Проверь: отрицания и условия сохранены; "
                         "модальность не усилена; субъект верный; чужая цитируемая позиция не выдана за вывод "
                         "авторов (нужен cited_from); гипотеза или намерение не выданы за результат; связь — не "
                         "причинность; выборка, страна, версия методики не расширены. Контекста мало — читай файл "
                         "источника дальше; не хватает и там — ставь unclear. Для аннотации не достраивай методы. "
                         "Ответ — JSON-список {id, hash, support, scope, note, problems, fix}; hash скопируй из пакета "
                         "без изменений."),
        "claims": out})
    print(f"review_packet.json: {len(out)} тезисов на рецензию")

elif a.apply:
    if not a.mode:
        sys.exit("нужен --mode: independent (отдельный агент) или self (самопроверка)")
    raw = load(d / "claims.json")
    by_id = {c["id"]: c for c in all_claims(raw)}
    reviews = load(a.apply, [])
    bad = []
    for r in reviews:
        c = by_id.get(r.get("id"))
        if not c:
            bad.append(f"{r.get('id')}: такого тезиса нет")
        elif r.get("support") not in SUPPORT or r.get("scope") not in SCOPE:
            bad.append(f"{r.get('id')}: support/scope вне допустимых значений")
        elif not r.get("hash"):
            bad.append(f"{r.get('id')}: нет hash из пакета — непонятно, какую версию тезиса проверял рецензент")
        elif r["hash"] != claim_hash(c):
            bad.append(f"{r.get('id')}: тезис изменился после выдачи пакета — нужен новый --packet и новая рецензия")
    if bad:
        sys.exit("рецензии не записаны:\n  " + "\n  ".join(bad))
    if raw.get("schema_version", 1) < 2:
        raw["schema_version"] = 2   # рецензии v2 → и проверки структуры v2 (карточки противоречий и др.)
        print("claims.json переведён на схему v2: check_claims.py теперь проверяет comparison, cited_from, scope")
    for r in reviews:
        c = by_id[r["id"]]
        c["review"] = {"support": r["support"], "scope": r["scope"], "mode": a.mode, "date": today(),
                       "note": r.get("note", ""), "problems": r.get("problems") or [], "fix": r.get("fix", ""),
                       "hash": r["hash"]}
    write_claims(raw)
    print(f"записано рецензий: {len(reviews)} (режим {a.mode})")

else:
    if not (a.reason or "").strip():
        sys.exit("нужна --reason: почему тезис исключён")
    raw = load(d / "claims.json")
    c = {x["id"]: x for x in all_claims(raw)}.get(a.exclude)
    if not c:
        sys.exit(f"нет тезиса {a.exclude}")
    c["status"] = "excluded"
    c["exclusion"] = {"reason": a.reason, "date": today(), "last_review": c.get("review")}
    if a.attempts is not None:
        c["exclusion"]["attempts"] = a.attempts
    write_claims(raw)
    print(f"{a.exclude}: исключён, остаётся в журнале")
