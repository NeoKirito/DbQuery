# -*- coding: utf-8 -*-
"""SQL safety normalization shared by form and dynamic-option validation."""


def normalize_sql_for_safety(sql):
    """Remove SQL comments without joining tokens that comments separated.

    Line-comment newlines are retained. Block comments become one space, with
    their original newlines retained so ``INTO/**/#Temp`` normalizes to
    ``INTO #Temp`` rather than ``INTO#Temp``. Comment markers inside quoted
    string or identifier literals are left untouched.
    """
    text = sql or ''
    output = []
    i = 0
    length = len(text)
    quote = None

    while i < length:
        char = text[i]
        if quote:
            output.append(char)
            if char == quote:
                # SQL escapes quote characters by doubling them.
                if i + 1 < length and text[i + 1] == quote:
                    output.append(text[i + 1])
                    i += 2
                    continue
                quote = None
            i += 1
            continue

        if char in ("'", '"', '`', '['):
            quote = ']' if char == '[' else char
            output.append(char)
            i += 1
            continue

        if char == '-' and i + 1 < length and text[i + 1] == '-':
            output.append(' ')
            i += 2
            while i < length and text[i] != '\n':
                i += 1
            if i < length:
                output.append('\n')
                i += 1
            continue

        if char == '/' and i + 1 < length and text[i + 1] == '*':
            output.append(' ')
            i += 2
            while i < length:
                if text[i] == '*' and i + 1 < length and text[i + 1] == '/':
                    i += 2
                    break
                if text[i] == '\n':
                    output.append('\n')
                i += 1
            continue

        output.append(char)
        i += 1

    return ''.join(output)


def sql_tokens_for_safety(sql):
    """Yield uppercase SQL word tokens outside literals, identifiers and comments.

    This intentionally treats single-quoted strings, double-quoted delimited
    identifiers, bracket identifiers, backticks and both SQL comment forms as
    opaque spans. It supports doubled quote escaping (``''``, ``\"\"`` and
    ``]]``), which prevents a keyword embedded in any quoted span from being
    mistaken for executable SQL syntax.
    """
    text = sql or ''
    tokens = []
    i = 0
    length = len(text)

    while i < length:
        char = text[i]

        if char == '-' and i + 1 < length and text[i + 1] == '-':
            i += 2
            while i < length and text[i] != '\n':
                i += 1
            continue

        if char == '/' and i + 1 < length and text[i + 1] == '*':
            i += 2
            while i < length:
                if text[i] == '*' and i + 1 < length and text[i + 1] == '/':
                    i += 2
                    break
                i += 1
            continue

        if char in ("'", '"', '`', '['):
            closing = ']' if char == '[' else char
            i += 1
            while i < length:
                if text[i] == closing:
                    if i + 1 < length and text[i + 1] == closing:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue

        if char.isalnum() or char in ('_', '@', '#', '$'):
            start = i
            i += 1
            while i < length and (text[i].isalnum() or text[i] in ('_', '@', '#', '$')):
                i += 1
            tokens.append(text[start:i].upper())
            continue

        i += 1

    return tokens


def contains_sql_keyword(sql, keyword):
    """Return whether a standalone executable SQL keyword is present.

    The comparison is case-insensitive and never inspects quoted spans or SQL
    comments. Consequently, it detects all identifier forms after ``INTO``
    without relying on the first character of the destination identifier.
    """
    expected = (keyword or '').upper()
    return bool(expected) and expected in sql_tokens_for_safety(sql)


_normalize_sql_for_safety = normalize_sql_for_safety
