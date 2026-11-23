# -*- coding: utf-8 -*-
"""SexKBJ -> TVBox/CatVod CMS facade (type 1).

为什么需要它：不少 FongMi / TVBox 版本根本不执行 Python 源（type 3），
所以把 sexkbj.com 的抓取逻辑搬到电脑上，盒子只当 type 1 读 JSON。

用法：
    python sexkbj_gateway.py --port 8081
    TVBox 条目：{"key":"sexkbj-lan","name":"SexKBJ[网关]","type":1,
                 "api":"http://<本机IP>:8081/api.php/provide/vod/",
                 "searchable":1,"quickSearch":1}
"""

import argparse
import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import requests

# packer.py 是已经和 node 逐字符对齐过的实现，直接复用，别在这里重写
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from packer import find_packer, unpack, grab_m3u8, grab_mp4  # noqa: E402

BASE = "https://sexkbj.com"
EMBED_HOST = "https://sexkbj.top"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/json,*/*",
           "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
PAGE_SIZE = 20
VER = "v1"

CATS = [("3", "韩国BJ"), ("966", "韩国素人"), ("95", "AfreecaTV"), ("12", "Premium")]

S = requests.Session()
S.headers.update(HEADERS)

_DETAIL = {}
_DETAIL_LOCK = threading.Lock()
_DETAIL_TTL = 1800
_PICS = {}


# ------------------------------------------------------------------ scrape ---
def _get(url, referer=None, timeout=12):
    h = {"Referer": referer} if referer else {}
    return S.get(url, headers=h, timeout=timeout)


def _text(html):
    if not html:
        return ""
    t = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#8217;", "'"),
                 ("&#039;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&#8211;", "-")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip()


def _clean_title(s):
    return re.sub(r"[_\s]*sexkbj\s*$", "", s or "", flags=re.I).strip()


def _pics(items):
    ids = [str(i.get("featured_media") or 0) for i in items]
    ids = [x for x in ids if x and x != "0"]
    if not ids:
        return {}
    key = ",".join(ids[:100])
    if key in _PICS:
        return _PICS[key]
    out = {}
    try:
        r = _get("%s/wp-json/wp/v2/media?include=%s&per_page=100&_fields=id,source_url"
                 % (BASE, key))
        for m in r.json():
            out[str(m["id"])] = m.get("source_url") or ""
    except Exception as e:
        print("[pics] %s" % e)
    _PICS[key] = out
    return out


def _rows(data, pics):
    rows = []
    for it in data:
        date = (it.get("date") or "")[:10]
        rows.append({
            "vod_id": str(it.get("id")),
            "vod_name": _clean_title(_text((it.get("title") or {}).get("rendered", ""))),
            "vod_pic": pics.get(str(it.get("featured_media") or ""), ""),
            "vod_remarks": date,
            "vod_year": date[:4],
            "vod_content": _text((it.get("excerpt") or {}).get("rendered", ""))[:300],
        })
    return rows


def listing(tid, pg):
    pg = max(1, int(pg or 1))
    url = ("%s/wp-json/wp/v2/posts?per_page=%d&page=%d"
           "&_fields=id,date,link,title,excerpt,featured_media" % (BASE, PAGE_SIZE, pg))
    if tid and str(tid).isdigit():
        url += "&categories=" + str(tid)
    r = _get(url)
    if r.status_code != 200:
        raise RuntimeError("wp http %d" % r.status_code)
    data = r.json()
    rows = _rows(data, _pics(data))
    try:
        pages = int(r.headers.get("X-WP-TotalPages") or 1)
    except Exception:
        pages = 1
    try:
        total = int(r.headers.get("X-WP-Total") or 0)
    except Exception:
        total = 0
    return rows, pg, pages, total


def search(wd, pg):
    pg = max(1, int(pg or 1))
    url = ("%s/wp-json/wp/v2/posts?per_page=%d&page=%d&search=%s"
           "&_fields=id,date,link,title,excerpt,featured_media"
           % (BASE, PAGE_SIZE, pg, quote(wd)))
    r = _get(url)
    if r.status_code != 200:
        return [], pg, 1, 0
    data = r.json()
    return _rows(data, _pics(data)), pg, 1, 0


def _play_of(js):
    u = grab_m3u8(js) or ""
    if not u:
        u = grab_mp4(js) or ""
    if not u:
        return ""
    # 行内可能被转义成 https:\/\/... 或 \u002F
    u = u.replace("\\/", "/").replace("\\u002F", "/")
    return u


def resolve_play(vod_id):
    """返回 (标题, 封面, 简介, 播放地址)。失败时播放地址为空字符串，绝不抛异常。"""
    now = time.time()
    with _DETAIL_LOCK:
        hit = _DETAIL.get(vod_id)
        if hit and now - hit[4] < _DETAIL_TTL:
            return hit[0], hit[1], hit[2], hit[3]

    title, pic, desc, play = "", "", "", ""
    try:
        r = _get(BASE + "/?p=" + vod_id, timeout=12)
        html = r.text or ""
        m = (re.search(r'<h1[^>]*class="[^"]*entry-title[^"]*"[^>]*>(.*?)</h1>', html, re.S | re.I)
             or re.search(r"<title>(.*?)</title>", html, re.S | re.I))
        if m:
            title = _clean_title(re.split(r"\s+[-|–]\s+", _text(m.group(1)))[0])
        p = re.search(r'<meta[^>]+(?:og:image|itemprop="thumbnailUrl")[^>]+content="([^"]+)"',
                      html, re.I)
        if p:
            pic = p.group(1)
        d = re.search(r'<meta[^>]+(?:og:description|name="description")[^>]+content="([^"]*)"',
                      html, re.I)
        if d:
            desc = d.group(1)[:400]
        e = re.search(r"https://sexkbj\.top/embed/([A-Za-z0-9_\-]+)", html, re.I)
        if e:
            try:
                eh = _get(EMBED_HOST + "/embed/" + e.group(1), referer=BASE + "/", timeout=10).text
                play = _play_of(unpack(find_packer(eh)) or "")
            except Exception as ex:
                print("[embed %s] %s: %s" % (vod_id, type(ex).__name__, ex))
    except Exception as ex:
        print("[detail %s] %s: %s" % (vod_id, type(ex).__name__, ex))

    with _DETAIL_LOCK:
        _DETAIL[vod_id] = (title, pic, desc, play, now)
    return title, pic, desc, play


# ------------------------------------------------------------------- server --
def class_list():
    """首页分类。少了这个客户端就没有分类入口 —— 只能看到推荐位。"""
    out = [{"type_id": "latest", "type_name": "最新"}]
    out += [{"type_id": c[0], "type_name": c[1]} for c in CATS]
    return out


def pack(rows, page=1, pages=1, total=0):
    return {"code": 1, "msg": "数据列表", "page": int(page), "pagecount": max(1, int(pages)),
            "limit": PAGE_SIZE, "total": int(total), "list": rows}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "sexkbj-gw/" + VER

    def log_message(self, fmt, *args):
        sys.stdout.write("[gw] %s %s\n" % (self.address_string(), fmt % args))
        sys.stdout.flush()

    def _send(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        try:
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path.startswith("/api.php"):
                return self.api(q)
            if u.path == "/":
                return self._send({"ok": True, "site": "sexkbj-gateway", "ver": VER,
                                   "api": "/api.php/provide/vod/",
                                   "cats": [{"id": c[0], "name": c[1]} for c in CATS]})
            return self._send({"code": 0, "msg": "not found"}, 404)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                self._send({"code": 0, "msg": "%s: %s" % (type(e).__name__, e)}, 500)
            except Exception:
                pass

    def api(self, q):
        ac = (q.get("ac") or [""])[0]
        pg = (q.get("pg") or ["1"])[0]
        t = (q.get("t") or [""])[0]
        ids = (q.get("ids") or [""])[0]
        wd = (q.get("wd") or [""])[0]

        if ids:
            out = []
            for vid in ids.split(","):
                vid = re.sub(r"[^0-9]", "", vid) or vid
                if not vid:
                    continue
                title, pic, desc, play = resolve_play(vid)
                out.append({
                    "vod_id": vid,
                    "vod_name": title or ("第 %s 号片" % vid),
                    "vod_pic": pic,
                    "vod_content": (desc or "") + ("\n[%s]" % VER),
                    "vod_play_from": "sexkbj",
                    "vod_play_url": ("第1集$" + play) if play else "",
                })
            return self._send(pack(out, 1, 1, len(out)))

        if wd:
            rows, page, pages, total = search(wd, pg)
            body = pack(rows, page, pages, total)
            body["class"] = class_list()
            body["filters"] = {}
            return self._send(body)

        if ac in ("flitter", "filter", "filters"):
            return self._send({"class": class_list(), "filters": {}})

        if not t:
            # 首页：class 一定要给，否则客户端只有推荐位、没有分类可进
            rows, page, pages, total = listing("", 1)
            body = pack(rows, page, pages, total)
            body["class"] = class_list()
            body["filters"] = {}
            return self._send(body)

        tid = "" if str(t) == "latest" else (str(t) if str(t).isdigit() else "")
        rows, page, pages, total = listing(tid, pg)
        body = pack(rows, page, pages, total)
        body["class"] = class_list()
        self._send(body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    try:
        r = _get(BASE + "/wp-json/wp/v2/posts?per_page=1&_fields=id", timeout=15)
        print("[pre] sexkbj.com http %d" % r.status_code)
    except Exception as e:
        print("[pre] sexkbj.com 连不上: %s: %s" % (type(e).__name__, e))
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("[gw] listening on %s:%d  ->  http://<LAN-IP>:%d/api.php/provide/vod/"
          % (args.host, args.port, args.port))
    srv.serve_forever()


if __name__ == "__main__":
    main()
