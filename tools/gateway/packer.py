# -*- coding: utf-8 -*-
"""Dean Edwards packer 的纯 Python 解包器（盒子端没有 node，所以不能用 node 解）。

用法:
    from packer import find_packer, unpack
    js = unpack(find_packer(html))
"""
import re

ALPHA = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _unbase(c, a):
    """复刻 JS 里的 e(c)：把序号 c 按 a 进制转成 packer 用的记号。"""
    if c < a:
        return ALPHA[c] if c < 36 else chr(c + 29)
    tail = chr(c % a + 29) if c % a > 35 else ALPHA[c % a]
    return _unbase(c // a, a) + tail


def find_packer(html):
    """从 HTML 里抠出 eval(function(p,a,c,k,e,d){...}(...)) 的括号内部分。"""
    start = html.find("eval(function(p,a,c,k,e,d)")
    if start < 0:
        start = html.find("eval(function (p,a,c,k,e,d)")
    if start < 0:
        return None
    i, depth = start + 4, 0
    while i < len(html):
        ch = html[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return html[start + 5:i]
        i += 1
    return None


def _tokens(s):
    """把参数串切成 (引号, 内容) 列表，支持单/双引号与裸数字。"""
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch in " \n\t,":
            i += 1
            continue
        if ch in "'\"":
            q, j, buf = ch, i + 1, []
            while j < len(s):
                if s[j] == "\\":
                    buf.append(s[j:j + 2])
                    j += 2
                    continue
                if s[j] == q:
                    break
                buf.append(s[j])
                j += 1
            out.append((q, "".join(buf)))
            i = j + 1
            continue
        j = i
        while j < len(s) and s[j] not in ",\n":
            j += 1
        out.append((None, s[i:j].strip()))
        i = j
    return out


def unpack(src):
    """src = find_packer(html) 的返回值；返回解包后的 JS 源码。"""
    m = re.match(r"^function\s*\(p,a,c,k,e,d\)\s*\{(.*)\}\((.*)\)$", src, re.S)
    if not m:
        raise ValueError("不是标准 packer")
    args = m.group(2)
    parts = _tokens(args)
    p = parts[0][1].encode().decode("unicode_escape")
    a = int(parts[1][1])
    c = int(parts[2][1])
    k = parts[3][1].split("|")
    if len(k) != c:
        raise ValueError("关键字个数不符 %d/%d" % (len(k), c))
    for i in range(c - 1, -1, -1):
        if k[i]:
            p = re.sub(r"\b" + re.escape(_unbase(i, a)) + r"\b", lambda _m, v=k[i]: v, p)
    return p


def grab_m3u8(js):
    m = re.search(r"https?://[^\"'\s]+\.m3u8[^\"'\s]*", js)
    return m.group(0) if m else None


def grab_mp4(js):
    m = re.search(r"https?://[^\"'\s]+\.mp4[^\"'\s]*", js)
    return m.group(0) if m else None
