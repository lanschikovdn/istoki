"""Разбор и проверка сценария аудиовыпуска (используется speak.py; без torch)."""
import re

REF = re.compile(r"\[([csp]\d+)\]")
# синтез и предложения звучат только в своих блоках, чтобы не смешаться с фактами;
# блок предложений — «Предложения ИИ» или «Наши предложения», не «…авторов»
LAYER_HEADER = {"s": re.compile(r"синтез|сопоставлен", re.I),
                "p": re.compile(r"^(наши предложения|предложения ии)\b", re.I)}
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


def parse(text, valid, engine):
    """Возвращает (blocks, speech, errors). blocks: (is_header, text, refs).

    valid: id → None, если на него можно ссылаться (допущенный тезис, верный синтез или
    предложение), иначе строка с причиной."""
    blocks, errors, header = [], [], ""
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s:
            continue
        if s.startswith("#"):
            header = s.lstrip("# ").strip()
            blocks.append((True, header, []))
            continue
        refs = REF.findall(s)
        other = [r for r in ANY_REF.findall(s) if not REF.fullmatch(r)]
        if other:
            errors.append(f"строка {n}: ссылки только вида [c4], [s1], [p1], а не {', '.join(other)}")
        if not refs:
            errors.append(f"строка {n}: нет ссылки на тезис — «{s[:60]}»")
        for r in refs:
            if r not in valid:
                errors.append(f"строка {n}: {r} нет в claims.json")
            elif valid[r]:
                errors.append(f"строка {n}: на {r} ссылаться нельзя — {valid[r]}")
            if r[0] in LAYER_HEADER and (not LAYER_HEADER[r[0]].search(header) or "автор" in header.lower()):
                need = "«Синтез»" if r[0] == "s" else "«Предложения ИИ» или «Наши предложения»"
                errors.append(f"строка {n}: {r} звучит только в блоке с заголовком {need}, а не «{header}»")
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
