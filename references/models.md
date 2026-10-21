# Модели информационного поиска → шаги навыка

Навык не ссылается на модели «для солидности». Каждая модель задаёт конкретное правило работы.

## Эллис: каркас конвейера

Ellis D. A behavioural approach to information retrieval system design // Journal of Documentation. 1989. Vol. 45, № 3. P. 171–212. DOI: 10.1108/eb026843
Ellis D., Cox D., Hall K. A comparison of the information seeking patterns of researchers in the physical and social sciences // Journal of Documentation. 1993. Vol. 49, № 4. P. 356–369. DOI: 10.1108/eb026919

| Действие по Эллису | Шаг навыка | Скрипт |
|---|---|---|
| Starting — первые источники | Запросы на русском и английском, карта темы | `map_topic.py` |
| Chaining — по ссылкам назад и по цитированиям вперёд | Обход от ядра | `chain.py` |
| Browsing — просмотр области | Списки авторов, площадок, ключевых слов в `map.md` | `map_topic.py` |
| Differentiating — отбор по качеству и значимости | Отбор кандидатов вместе с пользователем | `candidates.md` |
| Monitoring — слежение за новым | Цитирования вперёд, отсечка по году | `chain.py --from-year` |
| Extracting — извлечение | Дословные выписки из `sources/` | `claims.json` |
| Verifying — проверка точности | Сверка цитаты со строкой файла | `check_claims.py` |
| Ending — завершение | Страница, аудио, итог | `build_page.py`, `speak.py` |

## Бейтс: поиск меняется по ходу

Bates M. J. The design of browsing and berrypicking techniques for the online search interface // Online Review. 1989. Vol. 13, № 5. P. 407–424. DOI: 10.1108/eb024320

Правила:
- Запрос не фиксирован. Новые термины из найденных работ (ключевые слова OpenAlex, слова авторов) идут в следующий запрос. Каждое изменение запроса записывать в `map.md`, раздел «Журнал запросов».
- Ответ собирается по кусочкам из разных мест, а не одной выдачей.
- Тактики Бейтс и их аналоги:
  - footnote chasing (по сноскам) → обход ссылок назад;
  - citation searching (кто цитирует) → обход цитирований вперёд;
  - journal run (просмотр журнала) → площадки из `map.md`;
  - area scanning (просмотр соседних работ) → ключевые слова и темы OpenAlex;
  - author searching (по автору) → ключевые авторы из `map.md`.

## Култау: точка фокуса

Kuhlthau C. C. Inside the search process: Information seeking from the user's perspective // Journal of the American Society for Information Science. 1991. Vol. 42, № 5. P. 361–371. DOI: 10.1002/(SICI)1097-4571(199106)42:5<361::AID-ASI6>3.0.CO;2-#

Этапы ISP: начало (initiation) → выбор темы (selection) → исследование (exploration) → формулировка фокуса (formulation) → сбор (collection) → представление (presentation).

Правила:
- На этапе исследования неуверенность растёт. Массовый сбор до формулировки фокуса даёт кучу нерелевантного.
- Поэтому после карты темы **обязательная остановка**: показать пользователю черновик `map.md` и попросить выбрать фокус и ядро (5–15 работ). Только после этого — цепочки и скачивание.
- Фокус записывать в `map.md`, раздел «Фокус», словами пользователя.
