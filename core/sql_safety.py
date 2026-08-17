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


_normalize_sql_for_safety = normalize_sql_for_safety
