# -*- coding: utf-8 -*-
"""EroMe (www.erome.com) TVBox spider.

Route: scrape（站点不是 MacCMS，无公开 JSON 接口）
- 列表：/explore?page=N 与 /search?q=KEY&page=N
- 详情：/a/<id>，视频直链在 <source src="...mp4">，图片在 s*.erome.com
- 播放：CDN 需要 Referer: https://www.erome.com/a/<id>，否则 403
- DNS：部分 ISP 污染 www.erome.com，内置 DoH 兜底解析

内核基类：电视端把 py 当插件加载，必须继承 base.spider.Spider。
"""
import sys
import re
import json
import socket
import urllib.parse

try:
    sys.path.append('..')
    from base.spider import Spider as _Base
except Exception:
    class _Base(object):
        def __init__(self): pass

try:
    import requests
    from requests.packages.urllib3.exceptions import InsecureRequestWarning
    requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
except Exception:
    requests = None

VER = "v1"
BASE = "https://www.erome.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CATS = [
    ("latest", "最新"),
    ("search", "搜索"),
]

_ALBUM_RE = re.compile(r'<div class="[^"]*\balbum\b[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>', re.S)
_LINK_RE = re.compile(r'<a[^>]+class="album-link"[^>]+href="(https?://[^"]+/a/[A-Za-z0-9]+)"', re.S)
_IMG_RE = re.compile(r'<img[^>]+class="album-thumbnail[^"]*"[^>]+src="([^"]+)"', re.S)
_TITLE_RE = re.compile(r'<a[^>]+href="https://www\.erome\.com/a/[A-Za-z0-9]+"[^>]*>([^<]{1,200})</a>', re.S)
_USER_RE = re.compile(r'<span class="album-user"[^>]*>([^<]{1,80})</span>', re.S)
_SOURCE_RE = re.compile(r'<source[^>]+src="(https?://[^"]+?\.mp4[^"]*)"', re.S)
_H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)
_PAGE_RE = re.compile(r'href="[^"]*[?&]page=(\d+)"', re.S)


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or '')
    s = s.replace('&amp;', '&').replace('&quot;', '"').replace('&#039;', "'").replace('&lt;', '<').replace('&gt;', '>')
    return re.sub(r'\s+', ' ', s).strip()


def _doh(host):
    """用 Cloudflare DoH 解析真实 A 记录，绕开被污染的本地 DNS。"""
    try:
        if requests is None:
            return None
        r = requests.get("https://1.1.1.1/dns-query",
                         params={"name": host, "type": "A"},
                         headers={"accept": "application/dns-json"},
                         timeout=6, verify=False)
        for ans in (r.json().get("Answer") or []):
            if ans.get("type") == 1 and ans.get("data"):
                return ans["data"]
    except Exception:
        pass
    return None


class Spider(_Base):
    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass
        self._ip = {}
        self._ref = {}
        self._hdr = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

    # ---------- 基础请求 ----------
    def init(self, extend=""):
        return None

    def _raw_get(self, url, timeout=12):
        r = requests.get(url, headers=self._hdr, timeout=timeout, verify=False)
        if r.status_code == 200 and '<html' in r.text.lower():
            return r.text
        return None

    def _get(self, url, timeout=12):
        if requests is None:
            return None
        try:
            t = self._raw_get(url, timeout)
            if t:
                return t
        except Exception:
            pass
        # DNS 兜底：DoH 解析后 patch getaddrinfo 再试一次
        host = urllib.parse.urlsplit(url).hostname
        ip = self._ip.get(host) or _doh(host)
        if not ip:
            return None
        self._ip[host] = ip
        real = socket.getaddrinfo
        try:
            socket.getaddrinfo = lambda h, p, *a, **k: real(ip, p, *a, **k) if h == host else real(h, p, *a, **k)
            return self._raw_get(url, timeout)
        except Exception:
            return None
        finally:
            socket.getaddrinfo = real

    # ---------- 解析 ----------
    def _rows(self, html):
        rows = []
        if not html:
            return rows
        blocks = re.split(r'<div class="[^"]*\balbum\b[^"]*"\s+id="album-', html)[1:]
        for b in blocks:
            m = _LINK_RE.search(b) or re.search(r'href="(https?://[^"]+/a/[A-Za-z0-9]+)"', b)
            if not m:
                continue
            link = m.group(1)
            aid = link.rstrip('/').split('/')[-1]
            t = _TITLE_RE.search(b)
            pic = _IMG_RE.search(b)
            user = _USER_RE.search(b)
            rows.append({
                "vod_id": aid,
                "vod_name": _clean(t.group(1)) if t else aid,
                "vod_pic": pic.group(1) if pic else "",
                "vod_remarks": _clean(user.group(1)) if user else "",
            })
        # 去重
        seen, out = set(), []
        for r in rows:
            if r["vod_id"] in seen:
                continue
            seen.add(r["vod_id"])
            out.append(r)
        return out

    def _page_html(self, path):
        return self._get(BASE + path)

    # ---------- TVBox 六方法 ----------
    def homeContent(self, filter=True):
        return {"class": [{"type_id": k, "type_name": n} for k, n in CATS], "filters": {}}

    def homeVideoContent(self):
        return {"list": self._rows(self._page_html("/explore"))}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        pg = max(1, int(str(pg or 1)))
        if tid == "search":
            html = self._page_html("/explore?page=%d" % pg)
        else:
            html = self._page_html("/explore?page=%d" % pg)
        rows = self._rows(html)
        total = len(_PAGE_RE.findall(html or ""))
        return {"list": rows, "page": pg, "pagecount": 999, "limit": len(rows) or 20,
                "total": 9999, "msg": "pg%d" % pg}

    def searchContent(self, key, quick=False, pg="1"):
        pg = max(1, int(str(pg or 1)))
        q = urllib.parse.quote(str(key or ""))
        html = self._page_html("/search?q=%s&page=%d" % (q, pg))
        return {"list": self._rows(html), "page": pg, "pagecount": 999, "limit": 20, "total": 9999}

    def detailContent(self, ids):
        aid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
        if aid.startswith("http"):
            aid = aid.rstrip('/').split('/')[-1]
        url = "%s/a/%s" % (BASE, aid)
        html = self._get(url)
        if not html:
            return {"list": [{"vod_id": aid, "vod_name": "EroMe %s" % aid,
                              "vod_content": "[诊断] 详情页拉取失败（可能 DNS 被污染或站点不可达）"}]}
        h1 = _H1_RE.search(html)
        name = _clean(h1.group(1)) if h1 else aid
        t = re.search(r'<title>(.*?)</title>', html, re.S)
        if not h1 and t:
            name = _clean(t.group(1)).split(' - ')[0]
        srcs = []
        for s in _SOURCE_RE.findall(html):
            if s not in srcs:
                srcs.append(s)
        pics = [u for u in re.findall(r'https?://s\d+\.erome\.com/[^"\'\s]+\.(?:jpg|jpeg|png)', html)
                if '/thumbs/' not in u]
        poster = pics[0] if pics else ""
        lines = []
        for i, s in enumerate(srcs[:4]):
            lines.append("线路%d$%s" % (i + 1, s))
            self._ref[s] = url
        play_from = "EroMe" if lines else ""
        play_url = "#".join(lines)
        note = "[%s] 图片 %d 张" % (VER, len(pics))
        if not lines:
            note += "；该专辑没有视频（纯图集）"
        return {"list": [{
            "vod_id": aid,
            "vod_name": name,
            "vod_pic": poster,
            "vod_content": note,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }]}

    def playerContent(self, flag, id, vipFlags=None):
        url = id or ""
        hdr = {"User-Agent": UA}
        ref = self._ref.get(url)
        if not ref:
            m = re.search(r'/a/([A-Za-z0-9]+)', url)
            ref = ("%s/a/%s" % (BASE, m.group(1))) if m else (BASE + "/")
        hdr["Referer"] = ref
        return {"parse": 0, "playUrl": "", "url": url, "header": hdr, "jx": 0, "time": 0}
