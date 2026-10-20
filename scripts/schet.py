"""Считает в русском тексте формулы и привычки ИИ-письма и сравнивает с эталоном автора.

Примеры:
  python schet.py глава.md
  python schet.py рукопись/ --etalon посты/ --do-goda 2023
  python schet.py глава.md --etalon посты/ --mesta места.md --json счёт.json

Цитаты «…» и „…“ маскируются: дословную речь скрипт не считает.
Только стандартная библиотека Python 3.8+.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# ---------- шаблоны ----------
# (ключ, название, группа, регулярное выражение)
# группа: «против» — противопоставление; «подпись» — формула-подпись;
# «подпорка» — слово-подпорка; «регистр» — рекламный и машинный регистр, остатки чата;
# «ритм» — кандидаты для ручной проверки ритма; «голос» — приёмы живого автора (у ИИ их меньше),
# кроме тире: его у ИИ обычно больше.
P = [
    ("ne_a", "«не X, а Y»", "против",
     r"(?<![А-Яа-яё])[Нн]е (?!только|столько|просто так|раз|менее|более)[^.!?;:]{1,90}?, а (?!также|то |потом|затем|если|когда|ещё|значит)"),
    ("a_ne", "«Y, а не X»", "против", r", а не (?!только)"),
    ("ne_stolko", "«не столько X, сколько Y»", "против", r"\bне столько\b"),
    ("delo_ne_v", "«Дело (причина) не в X»", "против", r"\b(Дело|Причина|Суть|Проблема|Разница|Вопрос|Смысл) не в\b"),
    ("ee_ne_ee", "«увереннее, не точнее»", "против", r"\b[а-яё]+ее, не [а-яё]+ее\b"),
    ("eto_ne", "«Это не X, так (просто) Y»", "против",
     r"^(И )?(Это|Он|Она|Оно|Они) не [^.;:]{1,60}, (так|это|просто|скорее)\b"),
    ("i_eto", "хвост «…, и это …»", "подпись", r", и это\b"),
    ("i_est", "«X и есть Y»", "подпись", r"(?<!так )\bи есть\b"),
    ("v_tom_chto", "«Беда (причина, дело) в том, что»", "подпись",
     r"\b(Беда|Причина|Дело|Суть|Проблема|Разница|Фокус|Смысл|Секрет|Штука) в том, что"),
    ("otsyuda", "«Отсюда…» в начале фразы", "подпись", r"^Отсюда\b"),
    ("my_videli", "«как мы видели», «как выяснится»", "подпись",
     r"\b(как мы видели|мы видели|как выяснится|как мы увидим|мы ещё увидим|как мы уже говорили|как было показано)\b"),
    ("samyy", "«самый неожиданный (неприятный) вывод»", "подпись",
     r"\b[Сс]ам(ый|ое|ая|ого|ой|ую) (неприятн|неожиданн|интересн|показательн|удивительн|парадоксальн)\w*"),
    ("rovno", "«ровно» в значении «именно»", "подпись",
     r"\bровно\b(?! (один|одна|одно|одну|два|две|три|четыре|пять|столько|в \d|\d|половин|год|час|минут|сутки|неделю|месяц))"),
    ("tak_chto", "«так что»", "подпись", r"\bтак что\b"),
    ("zato", "«зато»", "подпись", r"\b[Зз]ато\b"),
    ("a_znachit", "«а значит»", "подпись", r"\bа значит\b"),
    ("vse_ravno", "«всё равно»", "подпись", r"\bвс[её] равно\b"),
    ("chestno", "оценочное «честно», «честный»", "подпись", r"\b[Чч]естн\w*"),
    ("meta", "мета: «стоит заметить», «важно отметить», «обратите внимание»", "подпись",
     r"\b([Сс]тоит заметить|[Вв]ажно отметить|[Вв]ажно понимать|[Зз]аметьте|[Оо]братите внимание|[Сс]тоит подчеркнуть|[Ии]нтересно, что|[Лл]юбопытно, что|[Пп]римечательно, что|[Нн]а самом деле)\b"),
    ("razvyazka", "двоеточие-развязка «Ответ простой:»", "подпись",
     r"\b(Ответ|Разгадка|Главное|Итог|Вывод|Объяснение|Причина|Правило|Секрет)( \w+)?:"),
    ("znachit", "«Значит,» в начале фразы", "подпись", r"^(А )?[Зз]начит,"),
    ("ramka", "рамка итога «Если собрать всё вместе», «Подводя итог»", "подпись",
     r"^(Если (свести|собрать|сложить) (всё|все|это) вместе|Подводя итоги?|В сухом остатке|Итак, |Суммируя|Резюмируя|Если коротко, )"),
    ("pochti", "«почти»", "подпорка", r"\b[Пп]очти\b"),
    ("edinstv", "«единственный»", "подпорка", r"\b[Ее]динственн\w*"),
    ("imenno", "«именно»", "подпорка", r"\b[Ии]менно\b"),
    ("to_est", "«то есть»", "подпорка", r"\b[Тт]о есть\b"),
    ("ni_ni", "«ни X, ни Y»", "подпорка", r"\b[Нн]и [^,.]{1,30}, ни\b"),
    ("vot", "«Вот и…», «Вот почему (как, что)»", "подпорка", r"\b[Вв]от (и|как|почему|что|чем|где|зачем)\b"),
    ("ne_prosto", "«не просто X. Это Y»", "против", r"\b[Нн]е просто\b(?! так)"),
    ("razduv", "раздувание значимости «знаковый момент»", "регистр",
     r"\b(знаков\w+ (момент|событи)|важн\w+ вех\w+|переломн\w+ (точк|момент)\w*|поворотн\w+ момент\w*|подчёркивает важность|закладывает основу|выходит на новый уровень|вывел\w* на новый уровень|изменил\w* всё|стал\w* настоящ\w+ прорыв\w*)"),
    ("deeprich", "деепричастный хвост «…, подчёркивая»", "регистр",
     r", (подчёркивая|отражая|демонстрируя|обеспечивая|формируя|укрепляя|открывая|задавая|символизируя|иллюстрируя|свидетельствуя)\b"),
    ("reklama", "рекламный регистр «уникальный», «богатейший опыт»", "регистр",
     r"\b([Пп]отрясающ|[Уу]никальн|[Бб]огатейш|[Нн]епревзойдённ|[Ии]нновационн|[Пп]рорывн|[Рр]еволюционн|[Бб]езупречн)\w*|может похвастаться|в самом сердце|по-настоящему"),
    ("bezym", "безымянная ссылка «исследования показывают»", "регистр",
     r"\b([Ии]сследования|[Ээ]ксперты|[Уу]чёные|[Сс]пециалисты|[Аа]налитики|[Нн]аблюдатели|[Мм]ногие) (показывают|считают|утверждают|отмечают|сходятся|доказали|уверены)|[Пп]ринято считать|[Пп]о имеющимся данным|[Пп]о мнению экспертов|[Кк]ак показывает практика"),
    ("slovar", "словарь машины «погрузимся», «раскрыть потенциал»", "регистр",
     r"\b([Пп]огрузимся|[Пп]огрузиться в|раскры\w+ (свой |весь )?потенциал|ландшафт\w*|экосистем\w*|синерги\w*|трансформаци\w*|переплетени\w*|служит свидетельством|выступает в роли|играет ключевую роль|новый этап|на новый уровень|ключев\w+ рол\w*)"),
    ("chat", "остатки чата «в этой главе мы рассмотрим», «надеюсь, это поможет»", "регистр",
     r"(В этой (главе|статье|части|разделе) (мы )?(рассмотрим|разберём|поговорим|узнаем)|[Дд]авайте (разберёмся|поговорим|рассмотрим|посмотрим)|Надеюсь, (это|эта|этот) (поможет|было полезно|будет полезн)|Отличный вопрос|Итак, приступим)"),
    ("shtamp", "штамп-разгон «не секрет, что», «в современном мире»", "регистр",
     r"([Вв] современном мире|[Вв] наши дни|[Вв] эпоху \w+|[Нн]е секрет, что|[Кк]ак известно|[Мм]ы все знаем|[Нн]ельзя не отметить|[Сс]ледует подчеркнуть|[Сс]тоит обратить внимание|[Хх]очется отметить|[Пп]режде всего, стоит)"),
    ("shutka", "объяснение шутки «согласитесь, иронично»", "регистр",
     r"(согласитесь|не правда ли|что, конечно, говорит о многом|довольно иронично|звучит иронично)"),
    ("final", "подпорка под вывод «в этом вся суть»", "регистр",
     r"([Вв] этом (и )?(вся|весь) (суть|секрет)|[Вв]от и весь секрет|[Ии]менно поэтому это работает|[Ии] это главное)"),
    ("diapazon", "«от X до Y» без чисел (проверить: ложный диапазон)", "ритм",
     r"\b[Оо]т (?!\d)[а-яё]{3,}( [а-яё]{2,}){0,3} до (?!\d)[а-яё]{3,}"),
    ("start_a", "фраза начинается с «А»", "голос", r"^А "),
    ("start_i", "фраза начинается с «И»", "голос", r"^И "),
    ("prosto", "«просто»", "голос", r"\b[Пп]росто\b"),
    ("tire", "длинное тире", "голос", r" — "),
]
# Пары фраз «Это не X. Это Y.»: первая фраза-отрицание и вторая, которая подхватывает
NE_FIRST = re.compile(r"^(Это |Он |Она |Оно |Они |Дело |Причина |Проблема |Вопрос )?(было |был |была |были )?[Нн]е ")
PICKUP = ("Это", "Он", "Она", "Оно", "Они", "Дело", "Причина", "Проблема", "Вопрос", "Всё", "Важно")

# Эталон по умолчанию: частоты на 10 тыс. слов в 384 постах одного автора
# нон-фикшн за 2016–2022 годы (54 тыс. слов по счёту этого скрипта, до ИИ). Годится только как
# грубый ориентир: лучше дать свой эталон через --etalon.
DEFAULT = {
    "ne_a": 15.1, "a_ne": 6.1, "ne_stolko": 0.6, "delo_ne_v": 0.0, "ee_ne_ee": 0.0, "eto_ne": 0.0,
    "i_eto": 0.0, "i_est": 0.9, "v_tom_chto": 0.0, "otsyuda": 0.0, "my_videli": 0.0, "samyy": 0.4,
    "rovno": 0.2, "tak_chto": 0.2, "zato": 0.4, "a_znachit": 0.2, "vse_ravno": 0.4, "chestno": 1.5,
    "meta": 2.0, "razvyazka": 0.2, "znachit": 0.0, "ramka": 0.6, "pochti": 1.1, "edinstv": 1.3, "imenno": 11.2,
    "to_est": 7.2, "ni_ni": 1.1, "vot": 1.3, "start_a": 23.1, "start_i": 25.1, "prosto": 9.2,
    "tire": 5.0, "ne_pair": 1.1, "ne_prosto": 1.3, "razduv": 0.0, "deeprich": 0.4, "reklama": 2.0,
    "bezym": 0.2, "slovar": 5.7, "chat": 0.0, "shtamp": 0.6, "shutka": 0.0, "final": 0.0, "diapazon": 1.7,
    "_dvoetochie": 18.2, "_tochka_zap": 1.5, "_dlina": 12.5, "_prigovor": 19.0, "_stakkato": 4.8,
    "_skleika": 27.3, "_odnoslov": 25.1, "_ogovorki": 0.2, "_troyki": 4.2,
}
HEDGE = re.compile(r"\b(пожалуй|возможно|вероятно|может быть|скорее всего|в некоторых случаях|в определённой степени|отчасти|по-видимому|как бы|в каком-то смысле|в известной мере)\b", re.I)
# три однородных члена по одно-два слова в конце фразы: «быстро, чётко, по делу»
TROYKA = re.compile(r"(?<![\w-])(?:(?:по|в|на|с|без|для) )?[А-Яа-яЁё-]{3,}, (?!котор|что|чтобы|это|если|когда|так |как )(?:(?:по|в|на|с|без|для) )?[а-яё-]{3,}(?:, | и |, и )(?:(?:по|в|на|с|без|для) )?[а-яё-]{3,}[.!?]$")
SPLIT = re.compile(r"(?<=[.!?…])\s+(?=[«„\"(]?[А-ЯЁA-Z0-9])")
WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+")


def mn(n, one, few, many):
    """Согласует слово с числом: 1 файл, 2 файла, 5 файлов."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def mask_quotes(s):
    """Заменяет содержимое «…» и „…“ на «_», чтобы цитаты не считались."""
    out, depth = [], 0
    for ch in s:
        if ch in "«„":
            depth += 1
            out.append(ch)
            continue
        if ch in "»“" and depth:
            depth -= 1
            out.append(ch)
            continue
        out.append("_" if depth else ch)
    return "".join(out)


def read_text(path, do_goda=None):
    t = path.read_text(encoding="utf-8", errors="ignore")
    if do_goda:
        m = re.search(r"^date:\s*['\"]?(\d{4})", t, re.M)
        if not m or int(m.group(1)) >= do_goda:
            return None
    t = re.sub(r"\A---\n.*?\n---\n", "", t, flags=re.S)  # frontmatter
    t = re.sub(r"```.*?```", "", t, flags=re.S)  # код
    return t


def collect(paths, do_goda=None):
    files = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            files += sorted(x for x in p.rglob("*") if x.suffix.lower() in (".md", ".txt"))
        elif p.exists():
            files.append(p)
        else:
            sys.exit(f"Нет такого файла или папки: {p}")
    docs = []
    for f in files:
        t = read_text(f, do_goda)
        if t is not None:
            docs.append((f, t))
    return docs


def sentences(docs):
    """Возвращает список абзацев: [(файл, строка, [фразы])]. Таблицы, заголовки, цитаты-блоки пропускаются."""
    paras = []
    for f, t in docs:
        for i, line in enumerate(t.split("\n"), 1):
            s = line.strip()
            # вывод docx_text.py из скила book-editing: «[12] {H1} текст» — номер абзаца вместо номера строки
            dx = re.match(r"^\[(\d+)\](?: \{([^}]*)\})? (.*)$", s)
            if dx:
                if (dx.group(2) or "").startswith(("H", "TITLE")):
                    continue
                i, s = int(dx.group(1)), dx.group(3).strip()
            if not s or s.startswith(("|", "#", ">", "<!--", "![", "---")):
                continue
            s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)  # маркер списка
            s = re.sub(r"[*_`]{1,3}", "", s) if not re.search(r"«[^»]*[*_]", s) else s.replace("**", "")
            paras.append((f, i, [x for x in SPLIT.split(s) if x.strip()]))
    return paras


def analyse(docs):
    paras = sentences(docs)
    words = sum(len(WORD.findall(s)) for _, _, ss in paras for s in ss) or 1
    hits = {k: [] for k, *_ in P}
    hits["ne_pair"] = []
    n_sent = n_colon = n_semi = 0
    lens = []
    prigovor, stakkato, skleika = [], [], []
    for f, ln, ss in paras:
        run = []
        for j, s in enumerate(ss):
            m = mask_quotes(s)
            w = len(WORD.findall(s))
            if not w:
                continue
            n_sent += 1
            lens.append(w)
            if ":" in m:
                n_colon += 1
            if ";" in m:
                n_semi += 1
            if w >= 22 and (";" in m or re.search(r"\w: [а-яё]", m)):
                skleika.append((f, ln, s))
            for k, _, _, pat in P:
                for _ in re.finditer(pat, m, flags=re.M):
                    hits[k].append((f, ln, s))
            if NE_FIRST.match(m) and w <= 14 and j + 1 < len(ss):
                nxt = ss[j + 1].split(" ")[0].strip("«„")
                first = m.split(" ")[0]
                if nxt in PICKUP or (nxt == first and first[0].isupper()):
                    hits["ne_pair"].append((f, ln, s + " " + ss[j + 1]))
            if w <= 6:
                run.append(s)
            else:
                if len(run) >= 3:
                    stakkato.append((f, ln, " ".join(run)))
                run = []
        if len(run) >= 3:
            stakkato.append((f, ln, " ".join(run)))
        if len(ss) >= 3:
            last = ss[-1]
            if len(WORD.findall(last)) <= 7 and not last.lstrip().startswith("«"):
                prigovor.append((f, ln, last))
    per = lambda n: round(n / words * 10000, 1)
    res = {"слов": words, "фраз": n_sent, "шаблоны": {}}
    names = {k: (name, grp) for k, name, grp, _ in P}
    names["ne_pair"] = ("пара фраз «Это не X. Это Y.»", "против")
    for k, (name, grp) in names.items():
        res["шаблоны"][k] = {"название": name, "группа": grp, "n": len(hits[k]), "на10тыс": per(len(hits[k]))}
    res["синтаксис"] = {
        "_dvoetochie": ("фраз с двоеточием, %", round(100 * n_colon / max(n_sent, 1), 1)),
        "_tochka_zap": ("фраз с точкой с запятой, %", round(100 * n_semi / max(n_sent, 1), 1)),
        "_dlina": ("средняя длина фразы, слов", round(sum(lens) / max(len(lens), 1), 1)),
        "_prigovor": ("короткая фраза-приговор в конце абзаца, на 10 тыс. слов", per(len(prigovor))),
        "_stakkato": ("серия из 3+ коротких фраз, на 10 тыс. слов", per(len(stakkato))),
        "_skleika": ("длинная фраза, склеенная «:» или «;», на 10 тыс. слов", per(len(skleika))),
    }
    # то, что не ловится одним шаблоном
    odnoslov, ogovorki, troyki, simspisok = [], [], [], []
    for f, ln, ss in paras:
        for s in ss:
            m = mask_quotes(s)
            if len(WORD.findall(s)) == 1 and not s.lstrip().startswith("«"):
                odnoslov.append((f, ln, s))
            if len(HEDGE.findall(m)) >= 2:
                ogovorki.append((f, ln, s))
            if TROYKA.search(m):
                troyki.append((f, ln, s))
    for f, t in docs:  # списки: три и больше пунктов подряд с одинаковым началом
        items = []
        for i, line in enumerate(t.split("\n") + [""], 1):
            mm = re.match(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)", line)
            if mm:
                items.append((i, mm.group(1)))
                continue
            if len(items) >= 3:
                heads = {" ".join(WORD.findall(x.lower())[:2]) for _, x in items}
                if len(heads) == 1:
                    simspisok.append((f, items[0][0], " / ".join(x for _, x in items)))
            items = []
    res["синтаксис"].update({
        "_odnoslov": ("фраза из одного слова («Зачем?», «Долго.»), на 10 тыс. слов", per(len(odnoslov))),
        "_ogovorki": ("стопка оговорок (2+ в одной фразе), на 10 тыс. слов", per(len(ogovorki))),
        "_troyki": ("тройка однородных в конце фразы (проверить: триплет), на 10 тыс. слов", per(len(troyki))),
        "_simspisok": ("список из 3+ пунктов с одинаковым началом, мест", len(simspisok)),
    })
    hits["_prigovor"], hits["_stakkato"], hits["_skleika"] = prigovor, stakkato, skleika
    hits["_odnoslov"], hits["_ogovorki"], hits["_troyki"], hits["_simspisok"] = odnoslov, ogovorki, troyki, simspisok
    return res, hits


def verdict(group, v, e, n):
    if e is None:
        return ""
    if group == "голос":
        if e and v < e / 2:
            return "у автора больше"
        if e and v >= 3 * e:
            return f"выше эталона ×{v / e:.1f}"
        return ""
    if e == 0:
        return "нет у автора" if n >= 2 else ("одно место" if n == 1 else "")
    r = v / e
    if r >= 3:
        return f"выше эталона ×{r:.1f}"
    if r >= 1.5:
        return f"следить ×{r:.1f}"
    return ""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tekst", nargs="+", help="файлы или папки с текстом (.md, .txt)")
    ap.add_argument("--etalon", nargs="+", help="тексты автора без ИИ (файлы или папки)")
    ap.add_argument("--do-goda", type=int, help="брать из эталона только файлы с date: раньше этого года")
    ap.add_argument("--bez-etalona", action="store_true", help="не сравнивать ни с чем, даже со встроенным ориентиром")
    ap.add_argument("--mesta", help="записать все найденные места в этот .md для ручного разбора")
    ap.add_argument("--json", help="записать полный счёт в JSON")
    a = ap.parse_args()

    docs = collect(a.tekst)
    if not docs:
        sys.exit("Текст пустой: нечего считать.")
    res, hits = analyse(docs)
    base, base_name = None, None
    if a.etalon:
        edocs = collect(a.etalon, a.do_goda)
        if not edocs:
            sys.exit("Эталон пустой: проверьте путь и --do-goda.")
        eres, _ = analyse(edocs)
        base = {k: v["на10тыс"] for k, v in eres["шаблоны"].items()}
        base.update({k: v[1] for k, v in eres["синтаксис"].items()})
        base_name = f"эталон: {mn(len(edocs), 'файл', 'файла', 'файлов')}, {mn(eres['слов'], 'слово', 'слова', 'слов')}"
    elif not a.bez_etalona:
        base, base_name = DEFAULT, "встроенный ориентир (посты одного автора нон-фикшн, 54 тыс. слов, до ИИ); свой эталон точнее"

    out = [f"# Счёт формул ИИ\n", f"Текст: {mn(len(docs), 'файл', 'файла', 'файлов')}, {mn(res['слов'], 'слово', 'слова', 'слов')}, {mn(res['фраз'], 'фраза', 'фразы', 'фраз')}."]
    if base_name:
        out.append(f"Сравнение: {base_name}.")
    if res["слов"] < 3000:
        out.append("Текст короче 3000 слов: частоты шумные, смотрите сами места (--mesta).")
    out.append("\nЧастота на 10 тыс. слов. «нет у автора» и «выше эталона» — кандидаты на правку; каждое место решается по контексту.\n")
    out.append("| Группа | Оборот | Мест | Текст | Эталон | Вывод |\n|---|---|---:|---:|---:|---|")
    order = {"против": 0, "подпись": 1, "подпорка": 2, "регистр": 3, "ритм": 4, "голос": 5}
    for k, v in sorted(res["шаблоны"].items(), key=lambda x: (order[x[1]["группа"]], -x[1]["n"])):
        e = base.get(k) if base else None
        if v["n"] == 0 and v["группа"] != "голос":
            continue
        vd = verdict(v["группа"], v["на10тыс"], e, v["n"]) if base else ""
        if v["группа"] == "против" and v["n"]:
            vd = "разобрать каждое место"
        if k == "bezym" and v["n"]:
            vd = "вопрос автору: кто и где"
        if v["группа"] == "ритм" and v["n"]:
            vd = "проверить вручную"
        out.append(f"| {v['группа']} | {v['название']} | {v['n']} | {v['на10тыс']} | {'' if e is None else e} | {vd} |")
    out.append("\n| Синтаксис | Текст | Эталон |\n|---|---:|---:|")
    for k, (name, val) in res["синтаксис"].items():
        e = base.get(k) if base else None
        out.append(f"| {name} | {val} | {'' if e is None else e} |")
    print("\n".join(out))

    if a.mesta:
        lines = ["# Места для разбора\n", "Каждое место решить по контексту: часть совпадений законна.\n"]
        allnames = {k: v["название"] for k, v in res["шаблоны"].items()}
        allnames.update({k: v[0] for k, v in res["синтаксис"].items()})
        for k, lst in hits.items():
            if not lst:
                continue
            lines.append(f"\n## {allnames.get(k, k)} ({len(lst)})\n")
            for f, ln, s in lst:
                lines.append(f"- `{f.name}:{ln}` {s.strip()}")
        Path(a.mesta).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"\nМеста записаны: {a.mesta}")
    if a.json:
        res["эталон"] = base
        res["места"] = {k: [{"файл": str(f), "строка": ln, "фраза": s} for f, ln, s in lst] for k, lst in hits.items()}
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"JSON: {a.json}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
