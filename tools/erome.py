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

VER = "v5"
BASE = "https://www.erome.com"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 登录 cookie（留空 = 游客，只看公开专辑）。
# 想用账号权限：把 erome_login.py 抓到的串粘到这里，或填到电视端该源的 extend 字段。
COOKIE = ""

# 只要带视频的专辑（卡片上有 class="album-videos" 的计数图标）
VIDEO_ONLY = True
# 一页不够 20 条视频专辑时，最多往后翻几页拼
MAX_PAGES = 4

CATS = [
    ("latest", "最新"),
    ("feed", "关注动态"),
    ("liked", "我赞过的"),
    ("search", "搜索"),
]

# 需要登录 cookie 才能有内容的分类（游客访问会返回 0 个专辑）
LOGIN_REQUIRED = ("feed", "liked")

_ALBUM_RE = re.compile(r'<div class="[^"]*\balbum\b[^"]*"[^>]*>.*?</div>\s*</div>\s*</div>', re.S)
_LINK_RE = re.compile(r'<a[^>]+class="album-link"[^>]+href="(https?://[^"]+/a/[A-Za-z0-9]+)"', re.S)
_IMG_RE = re.compile(r'<img[^>]+class="album-thumbnail[^"]*"[^>]+src="([^"]+)"', re.S)
_TITLE_RE = re.compile(r'<a[^>]+href="https://www\.erome\.com/a/[A-Za-z0-9]+"[^>]*>([^<]{1,200})</a>', re.S)
_USER_RE = re.compile(r'<span class="album-user"[^>]*>([^<]{1,80})</span>', re.S)
_VID_RE = re.compile(r'class="album-videos"[^>]*>.*?</svg>\s*(\d+)', re.S)
_PIC_RE = re.compile(r'class="album-images"[^>]*>.*?</svg>\s*(\d+)', re.S)
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
        self._cookie = COOKIE
        self._hdr = {
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        if self._cookie:
            self._hdr["Cookie"] = self._cookie

    # ---------- 基础请求 ----------
    def init(self, extend=""):
        """extend 可以放登录 cookie（两种写法都认）：
           1) 直接写 cookie 串：  PHPSESSID=xxx; other=yyy
           2) JSON：              {"cookie": "PHPSESSID=xxx; other=yyy"}
        """
        ext = (extend or "").strip()
        if not ext:
            return None
        if ext.startswith("{"):
            try:
                obj = json.loads(ext)
                ext = (obj.get("cookie") or "").strip()
            except Exception:
                pass
        if ext and "=" in ext:
            self._cookie = ext
            self._hdr["Cookie"] = ext
        return None

    def _raw_get(self, url, timeout=12):
        r = requests.get(url, headers=self._hdr, timeout=timeout, verify=False)
        if r.status_code == 200 and '<html' in r.text.lower():
            return r.text
        return None

    def _get(self, url, timeout=10):
        if requests is None:
            return None
        host = urllib.parse.urlsplit(url).hostname or ""
        # 先用 DoH 拿到真实 IP（首次约 0.3–0.8s），之后就固定走这个 IP
        ip = self._ip.get(host)
        if ip is None:
            ip = _doh(host)
            if ip:
                self._ip[host] = ip
        if ip:
            real = socket.getaddrinfo
            try:
                socket.getaddrinfo = lambda h, p, *a, **k: real(ip, p, *a, **k) if h == host else real(h, p, *a, **k)
                t = self._raw_get(url, timeout)
                if t:
                    return t
            except Exception:
                pass
            finally:
                socket.getaddrinfo = real
        # 兜底：不 patch 直接试（DNS 没被污染的环境走这条）
        try:
            return self._raw_get(url, timeout)
        except Exception:
            return None

    # ---------- 解析 ----------
    def _rows(self, html, video_only=None):
        """解析列表页。video_only=True 时只保留卡片上标了视频数的专辑。"""
        if video_only is None:
            video_only = VIDEO_ONLY
        rows = []
        if not html:
            return rows
        blocks = re.split(r'<div class="[^"]*\balbum\b[^"]*"\s+id="album-', html)[1:]
        for b in blocks:
            m = _LINK_RE.search(b) or re.search(r'href="(https?://[^"]+/a/[A-Za-z0-9]+)"', b)
            if not m:
                continue
            nvid = _VID_RE.search(b)
            npic = _PIC_RE.search(b)
            nv = int(nvid.group(1)) if nvid else 0
            np_ = int(npic.group(1)) if npic else 0
            if video_only and nv <= 0:
                continue
            link = m.group(1)
            aid = link.rstrip('/').split('/')[-1]
            t = _TITLE_RE.search(b)
            pic = _IMG_RE.search(b)
            user = _USER_RE.search(b)
            marks = []
            if nv:
                marks.append("视频%d" % nv)
            if np_:
                marks.append("图%d" % np_)
            if user:
                marks.append(_clean(user.group(1)))
            rows.append({
                "vod_id": aid,
                "vod_name": _clean(t.group(1)) if t else aid,
                "vod_pic": pic.group(1) if pic else "",
                "vod_remarks": " · ".join(marks),
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

    def _gather(self, make_path, pg, want=20):
        """从第 pg 页开始往后翻，凑够 want 条（只留视频专辑时一页可能不够）。"""
        rows, seen = [], set()
        p = pg
        for _ in range(MAX_PAGES):
            for r in self._rows(self._page_html(make_path(p)), self._video_only_flag):
                if r["vod_id"] not in seen:
                    seen.add(r["vod_id"])
                    rows.append(r)
            if len(rows) >= want:
                break
            p += 1
        return rows

    _video_only_flag = True

    # ---------- TVBox 六方法 ----------
    def homeContent(self, filter=True):
        return {"class": [{"type_id": k, "type_name": n} for k, n in CATS], "filters": {}}

    def homeVideoContent(self):
        return {"list": self._gather(lambda p: "/explore?page=%d" % p, 1, want=24)}

    def _note(self, text):
        return [{"vod_id": "note", "vod_name": text, "vod_pic": "", "vod_remarks": "提示"}]

    def categoryContent(self, tid, pg, filter=False, extend=""):
        pg = max(1, int(str(pg or 1)))
        tid = tid or "latest"

        if tid in LOGIN_REQUIRED and not self._cookie:
            return {"list": self._note(
                "「%s」需要登录：先跑 erome_login.py 抓 cookie，"
                "再填到本文件顶部 COOKIE 或本源的 extend 字段" % dict(CATS).get(tid, tid)),
                "page": pg, "pagecount": 1, "limit": 20, "total": 1}

        if tid == "latest":
            rows = self._gather(lambda p: "/explore?page=%d" % p, pg, want=24)
        elif tid == "feed":
            rows = self._gather(lambda p: "/user/feed?page=%d" % p, pg, want=24)
        elif tid == "liked":
            rows = self._gather(lambda p: "/user/liked?page=%d" % p, pg, want=24)
        elif tid == "search":
            rows = self._gather(lambda p: "/explore?page=%d" % p, pg, want=24)
        else:
            rows = self._gather(lambda p: "/explore?page=%d" % p, pg, want=24)

        if not rows and tid in LOGIN_REQUIRED:
            return {"list": self._note(
                "「%s」没有返回内容：cookie 可能已过期，或这个账号还没有关注/点赞" % dict(CATS).get(tid, tid)),
                "page": pg, "pagecount": 1, "limit": 20, "total": 1}
        return {"list": rows, "page": pg, "pagecount": 999, "limit": len(rows) or 20,
                "total": 9999, "msg": "pg%d" % pg}

    def searchContent(self, key, quick=False, pg="1"):
        pg = max(1, int(str(pg or 1)))
        q = urllib.parse.quote(str(key or ""))
        rows = self._gather(lambda p: "/search?q=%s&page=%d" % (q, p), pg, want=24)
        return {"list": rows, "page": pg, "pagecount": 999, "limit": len(rows) or 20, "total": 9999}

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
        ref = self._ref.get(url)
        if not ref:
            m = re.search(r'/a/([A-Za-z0-9]+)', url)
            ref = ("%s/a/%s" % (BASE, m.group(1))) if m else (BASE + "/")
        hdr = {"User-Agent": UA, "Referer": ref}
        if self._cookie:
            hdr["Cookie"] = self._cookie
        return {"parse": 0, "playUrl": "", "url": url, "header": hdr, "jx": 0, "time": 0}


