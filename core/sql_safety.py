# -*- coding: utf-8 -*-
"""SQL safety normalization shared by form and dynamic-option validation."""

TABLE_CONTEXT_KEYWORDS = frozenset((
    'FROM', 'JOIN', 'INTO', 'TABLE', 'UPDATE', 'INSERT', 'TRUNCATE', 'DROP', ',', '.'
))
PUNCTUATION_CHARS = frozenset(
    ('-', '=', '!', '*', '+', '%', '&', '|', '/', '\\', ':', ';', '?', '~', '^',
     '<', '>', '(', ')', '[', ']', '{', '}', "'", '"', '`')
)


def _is_hash_comment(text, index, last_token):
    """
    判断位置 index 处的 '#' 是否为行注释，还是 SQL Server 临时表标识符（如 #Temp, ##GlobalTemp）。
    规则：
    1. 若紧邻其后的字符为 EOF、换行、空白字符（空格/Tab），必为注释；
    2. 若紧邻其后的字符为非 ASCII（如中文字符，例：# 这是注释、#注释），必为注释；
    3. 若紧邻其后的字符为标点/非词法字符（如 - = ! * + : / ( 等），必为注释；
    4. 若紧随两个井号 '##'：
       - 若第三个字符为非字母数字下划线，必为注释；
       - 若第三个字符为字母数字下划线（例 ##GlobalTemp）：
         只有在上一个非注释 token 为表上下文关键字（FROM/JOIN/INTO/TABLE等）时才是临时表，否则为注释；
    5. 若后随普通标识符（如 #Temp、#AND、#WHERE、#SELECT）：
       - 若上一个非注释 token 为表上下文关键字（FROM/JOIN/INTO/TABLE等），判定为临时表标识符（非注释）；
       - 否则（如处于行首、语句首、或紧随 WHERE/SELECT/字段等之后），判定为行注释！
    """
    length = len(text)
    if index + 1 >= length:
        return True

    next_c = text[index + 1]
    if next_c in ('\r', '\n', ' ', '\t'):
        return True

    if ord(next_c) > 127 or next_c in PUNCTUATION_CHARS:
        return True

    if next_c == '#':
        third_c = text[index + 2] if index + 2 < length else ''
        if not third_c or third_c in ('\r', '\n', ' ', '\t') or ord(third_c) > 127 or third_c in PUNCTUATION_CHARS:
            return True
        if last_token and last_token.upper() in TABLE_CONTEXT_KEYWORDS:
            return False
        return True

    if last_token and last_token.upper() in TABLE_CONTEXT_KEYWORDS:
        return False

    return True


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
    last_token = None

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

        if char == '#' and _is_hash_comment(text, i, last_token):
            output.append(' ')
            i += 1
            while i < length and text[i] != '\n':
                i += 1
            if i < length:
                output.append('\n')
                i += 1
            continue

        if char.isalnum() or char in ('_', '@', '$') or char == '#':
            start = i
            i += 1
            while i < length and (text[i].isalnum() or text[i] in ('_', '@', '$', '#')):
                i += 1
            word = text[start:i]
            output.append(word)
            last_token = word.upper()
            continue

        if char in (',', '.'):
            last_token = char
        elif not char.isspace():
            last_token = char

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
    last_token = None

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

        if char == '#' and _is_hash_comment(text, i, last_token):
            i += 1
            while i < length and text[i] != '\n':
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

        if char.isalnum() or char in ('_', '@', '$') or char == '#':
            start = i
            i += 1
            while i < length and (text[i].isalnum() or text[i] in ('_', '@', '$', '#')):
                i += 1
            tok = text[start:i].upper()
            tokens.append(tok)
            last_token = tok
            continue

        if char in (',', '.'):
            last_token = char
        elif not char.isspace():
            last_token = char

        i += 1

    return tokens


def convert_hash_comments_to_sql(sql):
    """将 SQL 中作为行注释的 '#' 转换为 SQL Server 原生支持的 '-- ' 行注释。

    保留字符串常量、方括号/双引号标识符以及 #Temp 临时表。
    转换后的 SQL 可直接发送至 SQL Server 执行，避免语法错误。
    """
    text = sql or ''
    output = []
    i = 0
    length = len(text)
    quote = None
    last_token = None

    while i < length:
        char = text[i]
        if quote:
            output.append(char)
            if char == quote:
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
            output.append('--')
            i += 2
            while i < length and text[i] != '\n':
                output.append(text[i])
                i += 1
            continue

        if char == '/' and i + 1 < length and text[i + 1] == '*':
            output.append('/*')
            i += 2
            while i < length:
                if text[i] == '*' and i + 1 < length and text[i + 1] == '/':
                    output.append('*/')
                    i += 2
                    break
                output.append(text[i])
                i += 1
            continue

        if char == '#' and _is_hash_comment(text, i, last_token):
            output.append('--')
            i += 1
            while i < length and text[i] != '\n':
                output.append(text[i])
                i += 1
            continue

        if char.isalnum() or char in ('_', '@', '$') or char == '#':
            start = i
            i += 1
            while i < length and (text[i].isalnum() or text[i] in ('_', '@', '$', '#')):
                i += 1
            word = text[start:i]
            output.append(word)
            last_token = word.upper()
            continue

        if char in (',', '.'):
            last_token = char
        elif not char.isspace():
            last_token = char

        output.append(char)
        i += 1

    return ''.join(output)


def contains_sql_keyword(sql, keyword):
    """Return whether a standalone executable SQL keyword is present.

    The comparison is case-insensitive and never inspects quoted spans or SQL
    comments. Consequently, it detects all identifier forms after ``INTO``
    without relying on the first character of the destination identifier.
    """
    expected = (keyword or '').upper()
    return bool(expected) and expected in sql_tokens_for_safety(sql)


_normalize_sql_for_safety = normalize_sql_for_safety

