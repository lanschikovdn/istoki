"""Регрессионные тесты проверки цитат и сценария аудио. Запуск: python tests/test_core.py

Без сети и без torch. Для перевода чисел нужен num2words (иначе эти тесты пропускаются).
"""
import hashlib, json, pathlib, sys, tempfile, unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from check_claims import verify          # noqa: E402
from speak_check import parse            # noqa: E402

SOURCE = """<!-- istoki source: Ivanov2020_W1 -->
# Тестовая работа
- Статус: полный текст (PDF, 2 стр.)
---
[стр. 1]
Корреляция выгорания и стажа: r = -0,45 при p < 0,05.
В исследовании участвовали 1,5 тыс. учителей из 12 школ.
Эмоциональное выго-
рание чаще встречается у учителей начальной школы и
у социально-
психологических служб в конце учебного
[стр. 2]
года, по данным опроса.
Учителя отметили, что шкала понятна и проста в заполнении.
"""


def make(tmp, claims, status="полный текст (PDF, 2 стр.)", extra_files=None, tamper=False):
    d = pathlib.Path(tmp)
    (d / "sources").mkdir(parents=True, exist_ok=True)
    md = d / "sources" / "Ivanov2020_W1.md"
    md.write_text(SOURCE, encoding="utf-8")
    index = {"Ivanov2020_W1": {"status": status, "sha256": hashlib.sha256(md.read_bytes()).hexdigest(),
                               "authors": ["Иванов И. И."], "year": 2020}}
    for name, text in (extra_files or {}).items():
        (d / "sources" / f"{name}.md").write_text(text, encoding="utf-8")
    (d / "sources" / "index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    if tamper:
        md.write_text(SOURCE.replace("12 школ", "120 школ"), encoding="utf-8")
    (d / "claims.json").write_text(json.dumps(
        {"question": "t", "sections": [{"title": "s", "claims": claims}]}, ensure_ascii=False), encoding="utf-8")
    return d


def one(quote, line, source="Ivanov2020_W1", **kw):
    with tempfile.TemporaryDirectory() as tmp:
        c = {"id": "c1", "kind": "fact", "thesis": "т", "evidence": [{"source": source, "line": line, "quote": quote}]}
        claims, bad, _ = verify(make(tmp, [c], **kw))
        e = claims["sections"][0]["claims"][0]["evidence"][0]
        return bad == 0, e.get("error", ""), e


CASES = [
    # (описание, цитата, строка, ожидание, доп. параметры)
    ("верная цитата", "Корреляция выгорания и стажа: r = -0,45 при p < 0,05.", 6, True, {}),
    ("минус потерян", "Корреляция выгорания и стажа: r = 0,45 при p < 0,05.", 6, False, {}),
    ("знак < заменён на >", "Корреляция выгорания и стажа: r = -0,45 при p > 0,05.", 6, False, {}),
    ("1,5 → 15", "участвовали 15 тыс. учителей из 12 школ", 7, False, {}),
    ("типографский минус и «ёлочки» допустимы", "Корреляция выгорания и стажа: r = −0,45 при p < 0,05", 6, True, {}),
    ("не та строка", "участвовали 1,5 тыс. учителей из 12 школ", 6, False, {}),
    ("только знаки", "— — — —", 1, False, {}),
    ("с середины слова", "ителей из 12 школ и", 7, False, {}),
    ("с середины слова (текст есть)", "частвовали 1,5 тыс. учителей из 12 школ", 7, False, {}),
    ("обрыв слова в конце", "участвовали 1,5 тыс. учит", 7, False, {}),
    ("перенос по слогам", "Эмоциональное выгорание чаще встречается у учителей начальной школы", 8, True, {}),
    ("составное слово через перенос", "у социально-психологических служб в конце учебного года", 10, True, {}),
    ("через границу страниц", "в конце учебного года, по данным опроса", 11, True, {}),
    ("разложенная «й» (NFD)", unicodedata.normalize("NFD", "шкала понятна и проста в заполнении"), 14, True, {}),
    ("строка строкой", "участвовали 1,5 тыс. учителей из 12 школ", "7", True, {}),
    ("источник ПРОВЕРИТЬ", "участвовали 1,5 тыс. учителей из 12 школ", 7, False,
     {"status": "полный текст, ПРОВЕРИТЬ: название совпало на 20%"}),
    ("файл изменён после скачивания", "участвовали 1,5 тыс. учителей из 12 школ", 7, False, {"tamper": True}),
    ("файл не из fetch.py", "любая выдуманная фраза из файла", 1, False,
     {"source": "Fake_W9", "extra_files": {"Fake_W9": "любая выдуманная фраза из файла\n"}}),
]

fails = 0
for name, quote, line, want, kw in CASES:
    ok, err, e = one(quote, line, **kw)
    mark = "✓" if ok == want else "✗"
    fails += ok != want
    print(f"{mark} {name}: {'прошло' if ok else 'не прошло'}{' — ' + err if err else ''}")
    if name == "строка строкой" and ok and not isinstance(e["line"], int):
        fails += 1
        print("✗   номер строки не приведён к числу")

# противоречие из одного источника
with tempfile.TemporaryDirectory() as tmp:
    c = {"id": "c1", "kind": "contradiction", "thesis": "т", "evidence": [
        {"source": "Ivanov2020_W1", "line": 7, "quote": "участвовали 1,5 тыс. учителей из 12 школ"}]}
    _, bad, _ = verify(make(tmp, [c]))
    fails += bad != 1
    print(("✓" if bad == 1 else "✗") + " противоречие из одного источника: не прошло")

# сценарий аудио: id → None (можно ссылаться) или причина запрета
claims = {"c1": None, "c2": "тезис не допущен в основной слой"}
SPEAK = [
    ("ссылка на строку вместо тезиса", "Учителя выгорают. [Ivanov2020_W1:1]", False),
    ("тезис не допущен", "Учителя выгорают. [c2]", False),
    ("строка без ссылки", "Учителя выгорают.", False),
    ("греческая альфа", "Альфа Кронбаха α составила 0,87. [c1]", False),
    ("знак меньше", "Значимость p < 0,05. [c1]", False),
    ("число с окончанием", "В 1990-х годах шкалу адаптировали. [c1]", False),
    ("нормальная строка", "Корреляция составила −0,32 на выборке 1 200 человек, в 2017 году — 45%. [c1]", True),
]
try:
    import num2words  # noqa: F401
    have_n2w = True
except ImportError:
    have_n2w = False
    print("… num2words не установлен — проверки чисел пропущены")
for name, line, want in SPEAK:
    if not have_n2w and name in ("нормальная строка", "знак меньше", "греческая альфа", "число с окончанием"):
        continue
    blocks, speech, errors = parse(line, claims, "silero")
    ok = not errors
    fails += ok != want
    print(f"{'✓' if ok == want else '✗'} аудио, {name}: {'прошло' if ok else 'не прошло'}"
          f"{' — ' + errors[0] if errors else ''}")
    if name == "нормальная строка" and speech:
        s = speech[0]
        exp = ["минус ноль целых тридцать две сотых", "одна тысяча двести", "две тысячи семнадцатом году", "сорок пять процентов"]
        miss = [x for x in exp if x not in s]
        fails += bool(miss)
        print(f"{'✓' if not miss else '✗'}   озвучка: «{s}»" + (f" — нет: {miss}" if miss else ""))

print(f"\n{'ВСЕ ТЕСТЫ ПРОШЛИ' if not fails else f'ОШИБОК: {fails}'}")
sys.exit(1 if fails else 0)
