"""CSV files people open in Excel (D112).

Written so a Norwegian Excel opens them neatly in columns with æøå intact:
semicolon-separated (the list separator in a Norwegian locale), UTF-8 with a
byte-order mark (which tells Excel the encoding), Windows line endings.

Read forgivingly, so a file saved back from Excel or an older comma file still
works: either separator, UTF-8 (with or without the mark) or Windows-1252,
and an Excel «sep=;» first line is skipped.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

DELIMITER = ";"


def decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


def parse(text: str) -> list[dict]:
    lines = text.splitlines(keepends=True)
    if lines and lines[0].strip().lower().startswith("sep="):
        lines = lines[1:]
    header = lines[0] if lines else ""
    delimiter = ";" if header.count(";") >= header.count(",") and ";" in header else ","
    return list(csv.DictReader(io.StringIO("".join(lines), newline=""), delimiter=delimiter))


def read(path: Path) -> list[dict]:
    return parse(decode(Path(path).read_bytes()))


def dumps(header: list[str], rows) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=DELIMITER, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    return ("﻿" + out.getvalue()).encode("utf-8")


def write(path: Path, header: list[str], rows) -> None:
    Path(path).write_bytes(dumps(header, rows))
