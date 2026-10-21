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
"""
import argparse, bisect, hashlib, pathlib, re, sys, unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from common import load, save

KINDS = {"fact", "opinion", "definition", "method", "contradiction"}
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


def verify(d):
    """Проверяет claims.json заново. Возвращает (claims, число непрошедших тезисов, число выписок)."""
    d = pathlib.Path(d)
    claims = load(d / "claims.json")
    if not claims:
        sys.exit(f"нет {d / 'claims.json'}")
    index = load(d / "sources" / "index.json", {})
    cache, ids, bad, total = {}, set(), 0, 0
    for sec in claims.get("sections", []):
        for c in sec.get("claims", []):
            errs = []
            if c.get("id") in ids:
                errs.append(f"повтор id {c.get('id')}")
            ids.add(c.get("id"))
            if c.get("kind") not in KINDS:
                errs.append(f"неизвестный kind «{c.get('kind')}»")
            if not (c.get("thesis") or "").strip():
                errs.append("пустая подпись")
            ev = c.get("evidence") or []
            if not ev:
                errs.append("нет выписок")
            if c.get("kind") == "contradiction" and len({e.get("source") for e in ev}) < 2:
                errs.append("противоречию нужны выписки минимум из двух источников")
            oks = [check_evidence(d, e, index, cache) for e in ev]
            total += len(ev)
            c["errors"] = errs
            c["ok"] = not errs and all(oks)
            bad += not c["ok"]
    return claims, bad, total


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    a = ap.parse_args()
    d = pathlib.Path(a.dir)
    claims, bad, total = verify(d)
    n = 0
    for sec in claims.get("sections", []):
        for c in sec.get("claims", []):
            n += 1
            if not c["ok"]:
                print(f"✗ {c.get('id')}: {c.get('thesis', '')[:70]}")
                for m in c["errors"]:
                    print(f"    {m}")
                for e in c.get("evidence") or []:
                    if not e.get("ok"):
                        print(f"    {e.get('source')}:{e.get('line')} — {e.get('error')}")
    save(d / "claims.checked.json", claims)
    print(f"\nтезисов: {n}, прошли: {n - bad}, не прошли: {bad}; выписок: {total}")
    sys.exit(1 if bad else 0)
