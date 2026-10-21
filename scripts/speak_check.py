"""Разбор и проверка сценария аудиовыпуска (используется speak.py; без torch)."""
import re

REF = re.compile(r"\[(c\d+)\]")
ANY_REF = re.compile(r"\[[^\]]*\]")
# после перевода чисел Silero должен получить только кириллицу и знаки препинания
SILERO_OK = re.compile(r"[а-яёА-ЯЁ\s.,!?:;()«»\"'—–\-]")


def plural(n, one, few, many):
    n = abs(n) % 100
    if 11 <= n <= 14:
        return many
    return one if n % 10 == 1 else few if 2 <= n % 10 <= 4 else many


def say_numbers(t):
    from num2words import num2words

    def num(s):
        s = s.replace(",", ".")
        return num2words(float(s) if "." in s else int(s), lang="ru")

    def year(m):
        w = num2words(int(m.group(2)), lang="ru", to="ordinal").split()
        w[-1] = w[-1][:-2] + ("ьем" if w[-1].endswith("ий") else "ом")
        return f"{m.group(1)} {' '.join(w)} году"

    t = re.sub(r"(?<=\d)[   ](?=\d{3}(?!\d))", "", t)              # 1 200 → 1200
    t = re.sub(r"\b([Вв]о?)\s+(\d{4})\s+году\b", year, t)
    t = re.sub(r"(?<![\w\d])[-−–](?=\d)", "минус ", t)                       # −0,32 → минус …
    t = re.sub(r"(\d+(?:[,.]\d+)?)\s*%", lambda m: num(m.group(1)) + " " + (
        "процента" if re.search(r"[,.]", m.group(1)) else
        plural(int(m.group(1)), "процент", "процента", "процентов")), t)
    t = re.sub(r"\d+(?:,\d+)?", lambda m: num(m.group(0)), t)
    return t


def parse(text, claims_by_id, engine):
    """Возвращает (blocks, speech, errors). blocks: (is_header, text, refs)."""
    blocks, errors = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            blocks.append((True, s.lstrip("# ").strip(), []))
            continue
        refs = REF.findall(s)
        other = [r for r in ANY_REF.findall(s) if not REF.fullmatch(r)]
        if other:
            errors.append(f"строка {n}: ссылки только на тезисы вида [c4], а не {', '.join(other)}")
        if not refs:
            errors.append(f"строка {n}: нет ссылки на тезис — «{s[:60]}»")
        for r in refs:
            c = claims_by_id.get(r)
            if not c:
                errors.append(f"строка {n}: тезиса {r} нет в claims.json")
            elif not c.get("ok"):
                errors.append(f"строка {n}: тезис {r} не прошёл проверку")
        blocks.append((False, " ".join(ANY_REF.sub("", s).split()), refs))

    if engine != "silero":
        return blocks, [t for _, t, _ in blocks], errors
    speech = []
    for n, (_, t, _) in enumerate(blocks, 1):
        bad_num = re.findall(r"\d+-[а-яёa-z]+", t)
        if bad_num:
            errors.append(f"блок {n}: число с окончанием ({', '.join(bad_num)}) — запишите словами")
        try:
            sp = say_numbers(t)
        except ImportError:
            return blocks, [], errors + ["нет num2words: pip install num2words"]
        rest = sorted({ch for ch in sp if not SILERO_OK.match(ch)})
        if rest:
            errors.append(f"блок {n}: Silero молча пропустит символы {' '.join(rest)} — запишите словами "
                          f"(латиница, греческие буквы, знаки ≤ ≥ ± и т. п.)")
        speech.append(sp)
    return blocks, speech, errors
