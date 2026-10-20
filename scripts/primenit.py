"""Вносит правки «найти → заменить» из JSONL в файлы текста.

Каждая строка JSONL: {"id": "F1", "file": "глава-3.md", "find": "было", "replace": "стало"}
Правило безопасности: каждая цитата "find" должна найтись в своём файле ровно один раз.
Если хоть одна не нашлась или нашлась дважды, не меняется ни один файл.

Примеры:
  python primenit.py правки.jsonl                  # проверка, файлы не трогаются
  python primenit.py правки.jsonl --write          # внести, копии — в _копии до правки <дата>/
  python primenit.py правки.jsonl --write --koren рукопись/ --otchet было-стало.md

Файлы читаются и пишутся байтами: переводы строк и кодировка UTF-8 сохраняются.

Стилевая правка не должна менять факты. Поэтому скрипт отдельно выписывает правки,
где изменились числа, цитаты «…» или ссылки на главы: их надо сверить глазами.
Число вместо «почти» — законный случай, но и его стоит сверить с источником.
"""
import argparse
import datetime
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

GLAVA = re.compile(r"(?i)\b(перв|втор|трет|четв[её]рт|пят|шест|седьм|восьм|девят|десят|одиннадцат|двенадцат|тринадцат|четырнадцат|пятнадцат)\w*\s+глав\w*|\bглав\w*\s+\d+")


def invariants(s):
    """Числа, цитаты и ссылки на главы во фрагменте."""
    return {
        "числа": Counter(re.findall(r"\d+(?:[.,]\d+)?", s)),
        "цитаты": Counter(re.findall(r"«[^»]{3,}»", s)),
        "главы": Counter(m.group(0).lower() for m in GLAVA.finditer(s)),
    }


def changed(find, replace):
    a, b = invariants(find), invariants(replace)
    out = []
    for k in a:
        if a[k] != b[k]:
            gone = list((a[k] - b[k]).elements())
            new = list((b[k] - a[k]).elements())
            out.append(f"{k}: убрано {gone or '—'}, добавлено {new or '—'}")
    return out


def mn(n, one, few, many):
    """Согласует слово с числом: 1 правка, 2 правки, 5 правок."""
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} {one}"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} {few}"
    return f"{n} {many}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pravki", help="JSONL с правками")
    ap.add_argument("--koren", default=".", help="папка, от которой считаются пути file (по умолчанию текущая)")
    ap.add_argument("--write", action="store_true", help="внести правки (без флага — только проверка)")
    ap.add_argument("--otchet", help="записать список «было → стало» в этот .md")
    a = ap.parse_args()

    root = Path(a.koren)
    edits = []
    for n, line in enumerate(Path(a.pravki).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except json.JSONDecodeError as err:
            sys.exit(f"Строка {n}: не JSON ({err})")
        for k in ("file", "find", "replace"):
            if k not in e:
                sys.exit(f"Строка {n}: нет поля {k}")
        e.setdefault("id", f"#{n}")
        edits.append(e)

    data, errors = {}, []
    for e in edits:
        p = Path(e["file"])
        p = p if p.is_absolute() else root / p
        if p not in data:
            if not p.exists():
                errors.append(f"{e['id']}: нет файла {p}")
                continue
            data[p] = p.read_bytes().decode("utf-8")
        cnt = data[p].count(e["find"])
        if cnt != 1:
            errors.append(f"{e['id']}: в {p.name} цитата найдена {mn(cnt, 'раз', 'раза', 'раз')}, нужно ровно один: {e['find'][:80]!r}")
            continue
        if e["find"] == e["replace"]:
            errors.append(f"{e['id']}: замена совпадает с исходником")
            continue
        data[p] = data[p].replace(e["find"], e["replace"])
        e["_path"] = p

    if errors:
        print("Правки не внесены, исправьте файл правок:")
        print("\n".join("  " + x for x in errors))
        sys.exit(1)

    print(f"Проверено: {mn(len(edits), 'правка', 'правки', 'правок')}, файлов: {len(data)}; каждая цитата найдена ровно один раз.")
    facts = [(e["id"], c) for e in edits for c in [changed(e["find"], e["replace"])] if c]
    if facts:
        print(f"\nСверить с источником ({mn(len(facts), 'правка меняет', 'правки меняют', 'правок меняют')} числа, цитаты или ссылки на главы):")
        for i, c in facts:
            print(f"  {i}: " + "; ".join(c))
    if a.otchet:
        lines = ["# Было и стало\n"]
        for e in edits:
            lines.append(f"- **{e['id']}** *{e['_path'].name}.* **Было:** {e['find']}  \n  **Стало:** {e['replace']}")
        Path(a.otchet).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Список «было → стало»: {a.otchet}")
    if not a.write:
        print("Это проверка. Чтобы внести правки, добавьте --write.")
        return
    backup = root / f"_копии до правки {datetime.date.today().isoformat()}"
    for p, text in data.items():
        try:
            rel = p.resolve().relative_to(root.resolve())
        except ValueError:
            rel = Path(p.name)
        dst = backup / rel
        if not dst.exists():  # первая копия за день — это оригинал, её не перезаписываем
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
        p.write_bytes(text.encode("utf-8"))
    print(f"Внесено. Копии файлов до правки: {backup}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
