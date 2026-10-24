"""Проверка выписок: цитата действительно стоит в файле источника и начинается на указанной строке.

    python check_claims.py --dir <папка>

Читает <папка>/claims.json, пишет <папка>/claims.checked.json (для чтения человеком).
Код выхода 1, если есть ошибки. build_page.py и speak.py не верят этому файлу и
вызывают verify() заново.

Сравнение строгое ко всем буквам, цифрам и знакам (минус, <, >, запятая в числе).
Мягкое только к пробелам и переносам строк, переносу слова по слогам («выго-рание»),
виду кавычек и тире, лигатурам и форме Юникода. Метки [стр. N] не мешают цитате через
границу страниц. Цитата должна начинаться с начала слова на указанной строке.

Источник засчитывается, только если он есть в sources/index.json, его текст не менялся
с момента скачивания (sha256) и статус — «полный текст…» или «только аннотация».

Схема v2 (schema_version: 2) разделяет три проверки тезиса:
  1. точность цитаты — этот скрипт (поле ok);
  2. смысловая поддержка — рецензия: supported / partially_supported / unsupported / not_reviewed;
  3. границы применимости — рецензия: within_scope / overgeneralized / unclear / not_reviewed.
В основной слой (admitted) идёт тезис, у которого цитаты верны, рецензия свежая
(хеш подписи и выписок не менялся) и оба статуса рецензии — supported и within_scope.
Старый проект без рецензий открывается, но ни один тезис не допускается.
Синтез (слой B) и предложения (слой C) опираются только на допущенные тезисы.
"""
import argparse, bisect, hashlib, json, pathlib, re, sys, unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import load, save

KINDS = {"fact", "opinion", "definition", "method", "contradiction"}
SCHEMA = 2
SUPPORT = {"supported", "partially_supported", "unsupported", "not_reviewed"}
SCOPE = {"within_scope", "overgeneralized", "unclear", "not_reviewed"}
MODES = {"independent", "self"}          # независимый агент / повторная самопроверка
CONTRA_TYPES = {"direct", "different_conditions", "different_definitions", "insufficient_data"}
SCOPE_KEYS = {"sample", "country", "language", "instrument", "design", "outcomes"}
CHARMAP = str.maketrans({"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
                         "­": "", "«": '"', "»": '"', "„": '"', "“": '"', "”": '"', "‟": '"', "″": '"',
                         "‘": "'", "’": "'", "‚": "'", "′": "'", "‐": "-", "‑": "-", "‒": "-", "–": "-",
                         "—": "-", "―": "-", "−": "-"})
PAGE = re.compile(r"^\[стр\. \d+\]$")
LETTER_HYPHEN = re.compile(r"(?<=[^\W\d_])-(?=[^\W\d_])")


def canon(s, spaces=False):
    """Каноническая форма для сравнения. spaces=True оставляет одиночные пробелы (для границ слов)."""
    s = unicodedata.normalize("NFKC", s).translate(CHARMAP).lower().replace("ё", "е")
    s = re.sub(r"\s+", " " if spaces else "", s)
    s = re.sub(r"(?<=[^\W\d_])- (?=[^\W\d_])", "-", s)      # «выго- рание» после склейки строк
    return LETTER_HYPHEN.sub("", s).strip()


def usable(status):
    return status.startswith("полный текст (") or status == "только аннотация"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Source:
    def __init__(self, path):
        self.lines = path.read_text(encoding="utf-8").splitlines()
        parts = ["" if PAGE.match(ln.strip()) else canon(ln) for ln in self.lines]
        # перенос по слогам на стыке строк: «выго-» + «рание» — дефис убираем (внутри строки его убрал canon)
        nxt = ""
        for i in range(len(parts) - 1, -1, -1):
            p = parts[i]
            if len(p) > 1 and p.endswith("-") and p[-2].isalpha() and nxt[:1].isalpha():
                parts[i] = p[:-1]
            if parts[i]:
                nxt = parts[i]
        self.starts, pos = [], 0
        for p in parts:
            self.starts.append(pos)
            pos += len(p)
        self.text = "".join(parts)

    def line_of(self, off):
        return bisect.bisect_right(self.starts, off)   # 1-based

    def find_all(self, q):
        out, i = [], self.text.find(q)
        while i >= 0:
            out.append(i)
            i = self.text.find(q, i + 1)
        return out

    def spaced(self, a, b):
        body = [ln for ln in self.lines[a - 1:b] if not PAGE.match(ln.strip())]
        return canon("\n".join(body), spaces=True)


def check_evidence(d, e, index, cache):
    """Заполняет e['ok'], e['error'] / e['line_end'], e['context']. Возвращает True/False."""
    for k in ("ok", "error", "line_end", "context", "warning"):
        e.pop(k, None)
    key = e.get("source") or ""
    p = d / "sources" / f"{key}.md"
    meta = index.get(key)
    if not p.exists() or not meta:
        e["ok"], e["error"] = False, "источника нет в sources/index.json (файл не из fetch.py)"
        return False
    e["source_status"] = meta.get("status", "")
    if not usable(e["source_status"]):
        e["ok"], e["error"] = False, f"источник нельзя цитировать: «{e['source_status']}»"
        return False
    if meta.get("sha256") and meta["sha256"] != sha(p):
        e["ok"], e["error"] = False, "файл источника изменён после скачивания"
        return False
    try:
        L = int(e.get("line"))
    except (TypeError, ValueError):
        e["ok"], e["error"] = False, f"номер строки не число: {e.get('line')!r}"
        return False
    e["line"] = L
    quote = e.get("quote") or ""
    words = re.findall(r"[^\W_]+", quote)
    q = canon(quote)
    if len(words) < 4 or len(q) < 15:
        e["ok"], e["error"] = False, "цитата короче 4 слов"
        return False
    if key not in cache:
        cache[key] = Source(p)
    s = cache[key]
    hits = s.find_all(q)
    first = canon(words[0], spaces=True)
    last = canon(words[-1], spaces=True)
    for h in hits:
        if s.line_of(h) != L:
            continue
        end = s.line_of(h + len(q) - 1)
        win = s.spaced(L, end)
        # граница слова в начале (на строке L) и в конце цитаты
        if not re.search(r"(?<![^\W_])" + re.escape(first), canon(s.lines[L - 1], spaces=True)):
            continue
        if not re.search(re.escape(last) + r"(?![^\W_])", win):
            continue
        e.update(ok=True, line_end=end,
                 context={"from": max(1, L - 2), "lines": s.lines[max(0, L - 3):min(len(s.lines), end + 2)]})
        if len(words) > 60:
            e["warning"] = f"цитата длиннее 60 слов ({len(words)})"
        return True
    if hits:
        where = sorted({s.line_of(h) for h in hits})
        e["ok"] = False
        e["error"] = (f"цитата начинается на строке {', '.join(map(str, where[:5]))}, а не {L}" if L not in where
                      else "цитата начинается не с начала слова или обрывает слово")
    else:
        e["ok"], e["error"] = False, "цитаты нет в файле (текст изменён или источник не тот)"
    return False


def claim_hash(c):
    """Хеш того, что проверяет рецензент: подпись, вид, выписки, вторичность, границы, сопоставление."""
    def ln(x):
        try:
            return int(x)
        except (TypeError, ValueError):
            return x
    body = {"thesis": c.get("thesis"), "kind": c.get("kind"),
            "evidence": [[e.get("source"), ln(e.get("line")), e.get("quote")] for e in c.get("evidence") or []],
            "cited_from": c.get("cited_from"), "scope": c.get("scope"), "comparison": c.get("comparison")}
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def all_claims(claims):
    return [c for sec in claims.get("sections", []) for c in sec.get("claims", [])]


def structure_errors(c):
    """Поля схемы v2: карточка сопоставления у противоречия, вторичность, границы."""
    errs = []
    if c.get("kind") == "contradiction":
        cmp_ = c.get("comparison") or {}
        if not (cmp_.get("question") or "").strip():
            errs.append("противоречию нужна карточка comparison с общим вопросом")
        if not isinstance(cmp_.get("same"), list) or not isinstance(cmp_.get("different"), list):
            errs.append("comparison: нужны списки same (что совпадает) и different (что различается)")
        if cmp_.get("type") not in CONTRA_TYPES:
            errs.append(f"comparison.type — одно из: {', '.join(sorted(CONTRA_TYPES))}")
    cf = c.get("cited_from")
    if cf is not None and not (isinstance(cf, dict) and (cf.get("original") or "").strip()):
        errs.append("cited_from: нужен объект с полем original — чью позицию пересказывает источник")
    sc = c.get("scope")
    if sc is not None:
        if not isinstance(sc, dict):
            errs.append("scope должен быть объектом")
        elif set(sc) - SCOPE_KEYS:
            errs.append(f"scope: неизвестные поля {', '.join(sorted(set(sc) - SCOPE_KEYS))}")
    return errs


def review_state(c):
    """Возвращает (state, причины недопуска). state: fresh / stale / missing / invalid."""
    rv = c.get("review")
    if not rv:
        return "missing", ["нет содержательной рецензии"]
    if not isinstance(rv, dict):
        return "invalid", ["review должен быть объектом — записывать только через review.py --apply"]
    why = []
    if rv.get("support") not in SUPPORT:
        why.append(f"review.support — одно из: {', '.join(sorted(SUPPORT))}")
    if rv.get("scope") not in SCOPE:
        why.append(f"review.scope — одно из: {', '.join(sorted(SCOPE))}")
    if rv.get("mode") not in MODES:
        why.append("review.mode — independent или self")
    if why:
        return "invalid", why
    if rv.get("hash") != claim_hash(c):
        return "stale", ["рецензия устарела: подпись или выписки изменились после неё"]
    if rv["support"] != "supported":
        why.append(f"смысловая поддержка: {rv['support']}")
    if rv["scope"] != "within_scope":
        why.append(f"границы применимости: {rv['scope']}")
    return "fresh", why


def check_layer(items, prefix, allowed, required):
    """Синтез (s…) и предложения (p…): опоры — только из allowed (допущенные тезисы / верный синтез)."""
    seen = set()
    for it in items:
        errs = []
        iid = it.get("id") or ""
        if not re.fullmatch(prefix + r"\d+", iid):
            errs.append(f"id должен быть вида {prefix}1")
        if iid in seen:
            errs.append(f"повтор id {iid}")
        seen.add(iid)
        for f in required:
            if not it.get(f):
                errs.append(f"нет поля {f}")
        for f in ("basis", "assumptions"):   # списки непустых строк
            v = it.get(f)
            if v is not None and not (isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)):
                errs.append(f"{f} — список непустых строк")
        for r in it.get("basis") or []:
            if r not in allowed:
                errs.append(f"опора {r} не допущена в основной слой или не существует")
        it["errors"], it["ok"] = errs, not errs


def verify(d):
    """Проверяет claims.json заново. Возвращает (claims, число тезисов с ошибками, число выписок).

    Считаются только активные тезисы. «Ошибка» — неверная цитата или структура; отсутствие
    рецензии — не ошибка, а недопуск в основной слой (поле admitted)."""
    d = pathlib.Path(d)
    claims = load(d / "claims.json")
    if not claims:
        sys.exit(f"нет {d / 'claims.json'}")
    version = claims.get("schema_version", 1)
    if not isinstance(version, int) or version > SCHEMA:
        sys.exit(f"claims.json: схема {version!r} новее, чем понимает скрипт (до {SCHEMA}). Обновите навык.")
    index = load(d / "sources" / "index.json", {})
    cache, ids, bad, total = {}, set(), 0, 0
    for c in all_claims(claims):
        errs = []
        if c.get("id") in ids:
            errs.append(f"повтор id {c.get('id')}")
        ids.add(c.get("id"))
        if c.get("status", "active") == "excluded":
            ex = c.get("exclusion") or {}
            c["errors"] = [] if (ex.get("reason") or "").strip() else ["исключённому тезису нужна exclusion.reason"]
            c["ok"] = c["admitted"] = False
            c["review_state"], c["not_admitted"] = "excluded", ["исключён: " + (ex.get("reason") or "")]
            bad += bool(c["errors"])
            continue
        if c.get("kind") not in KINDS:
            errs.append(f"неизвестный kind «{c.get('kind')}»")
        if not (c.get("thesis") or "").strip():
            errs.append("пустая подпись")
        ev = c.get("evidence") or []
        if not ev:
            errs.append("нет выписок")
        if c.get("kind") == "contradiction" and len({e.get("source") for e in ev}) < 2:
            errs.append("противоречию нужны выписки минимум из двух источников")
        if version >= 2:
            errs += structure_errors(c)
        oks = [check_evidence(d, e, index, cache) for e in ev]
        total += len(ev)
        c["errors"] = errs
        c["ok"] = not errs and all(oks)
        bad += not c["ok"]
        state, why = review_state(c)
        if version < 2:   # старая схема: структура v2 не проверена → допуска нет
            why = why + ["старая схема claims.json: нужен schema_version 2 (его ставит review.py --apply)"]
        c["review_state"] = state
        c["not_admitted"] = ([] if c["ok"] else ["цитата или структура не прошли проверку"]) + why
        c["admitted"] = c["ok"] and state == "fresh" and not why
    admitted = {c["id"] for c in all_claims(claims) if c.get("admitted")}
    synth = claims.get("synthesis") or []
    check_layer(synth, "s", admitted, ("text", "basis", "limits"))   # синтез — только на тезисах: циклов нет
    ok_synth = {s["id"] for s in synth if s["ok"]}
    check_layer(claims.get("proposals") or [], "p", admitted | ok_synth,
                ("text", "basis", "assumptions", "not_checked", "pilot"))
    return claims, bad, total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    d = pathlib.Path(a.dir)
    claims, bad, total = verify(d)
    active = [c for c in all_claims(claims) if c.get("status", "active") != "excluded"]
    for c in all_claims(claims):
        if c.get("status") == "excluded" and c["errors"]:
            print(f"✗ {c.get('id')} (исключён): " + "; ".join(c["errors"]))
    for c in active:
        if not c["ok"]:
            print(f"✗ {c.get('id')}: {c.get('thesis', '')[:70]}")
            for m in c["errors"]:
                print(f"    {m}")
            for e in c.get("evidence") or []:
                if not e.get("ok"):
                    print(f"    {e.get('source')}:{e.get('line')} — {e.get('error')}")
    layer_bad = 0
    for it in (claims.get("synthesis") or []) + (claims.get("proposals") or []):
        if not it["ok"]:
            layer_bad += 1
            print(f"✗ {it.get('id')}: " + "; ".join(it["errors"]))
    save(d / "claims.checked.json", claims)
    st = lambda k: sum(1 for c in active if c["review_state"] == k)
    rejected = sum(1 for c in active if c["ok"] and c["review_state"] == "fresh" and not c["admitted"])
    print(f"\nтезисов: {len(active)} (исключено: {len(all_claims(claims)) - len(active)}); "
          f"цитаты верны: {sum(1 for c in active if c['ok'])}, ошибки: {sum(1 for c in active if not c['ok'])}; "
          f"выписок: {total}")
    print(f"допущено в основной слой: {sum(1 for c in active if c['admitted'])}; без рецензии: {st('missing')}, "
          f"рецензия устарела: {st('stale')}, рецензия с ошибкой формата: {st('invalid')}, рецензия не пропустила: {rejected}")
    if claims.get("synthesis") or claims.get("proposals"):
        print(f"синтез: {len(claims.get('synthesis') or [])}, предложения: {len(claims.get('proposals') or [])}, "
              f"с ошибками: {layer_bad}")
    sys.exit(1 if bad or layer_bad else 0)
