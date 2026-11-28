# -*- coding: utf-8 -*-
# XOJAV.TV -> TVBox py 源（替代原来的 csp_GM 版本）
# 站点没有分页（列表页固定 24 条，翻页 403），因此 pagecount 固定 1；搜索接口是 /?s=<关键词>
import html as _html
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request

try:
    sys.path.append('..')
    from base.spider import Spider as _Base  # noqa
except Exception:
    class _Base(object):
        def __init__(self, *a, **k):
            pass

VER = "v1"
BASE = "https://xojav.tv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

CATS = [
    ("latest-updates", "最近更新"),
    ("hot", "热门影片"),
    ("categories/taiwan-av", "台湾AV"),
    ("categories/uncensored", "无码解放"),
    ("categories/chinese-subtitle", "中文字幕"),
    ("categories/bdsm", "主奴调教"),
]

CARD_RE = re.compile(
    r'<a href="(https://xojav\.tv/videos/(?P<id>[A-Za-z0-9_\-]+))">\s*'
    r'<img[^>]*?data-src="(?P<pic>[^"]+)"[^>]*?alt="(?P<name>[^"]*)"[^>]*>'
    r'.*?card-video__duration">(?P<dur>[^<]*)<', re.S)


class Spider(_Base):
    def __init__(self, *a, **k):
        try:
            super(Spider, self).__init__(*a, **k)
        except Exception:
            pass
        self._hdr = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

    # ---------- 基础 ----------
    def getName(self):
        return "XOJAV"

    def init(self, extend=""):
        try:
            if extend and extend.strip().startswith("{"):
                j = json.loads(extend)
                self._hdr.update(j.get("headers") or {})
        except Exception:
            pass

    def _get(self, url, timeout=25):
        req = urllib.request.Request(url, headers=self._hdr)
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            return r.read().decode("utf-8", "ignore")

    # ---------- 解析 ----------
    def _rows(self, html):
        rows = []
        seen = set()
        for m in CARD_RE.finditer(html):
            vid = m.group("id")
            if vid in seen:
                continue
            seen.add(vid)
            rows.append({
                "vod_id": vid,
                "vod_name": _html.unescape(m.group("name")).strip(),
                "vod_pic": m.group("pic"),
                "vod_remarks": (m.group("dur") or "").strip(),
            })
        return rows

    def _detail(self, vid):
        url = "%s/videos/%s" % (BASE, vid)
        html = self._get(url)
        name = self._meta(html, "og:title") or vid
        pic = self._meta(html, "og:image")
        desc = self._meta(html, "og:description") or ""
        tags = re.findall(r'<meta property="video:tag" content="([^"]+)"', html)
        actors = re.findall(r'<meta property="video:actor" content="([^"]+)"', html)
        dur = ""
        m = re.search(r'class="[^"]*duration[^"]*"[^>]*>\s*([0-9:]{3,8})', html)
        if m:
            dur = m.group(1)
        play = ""
        m = re.search(r'(https://[a-z0-9.]*hshdkshd\.com/hls/[^"\'\s<>]+?\.m3u8[^"\'\s<>]*)', html)
        if m:
            play = m.group(1).replace("\\/", "/")
        if not play:
            m = re.search(r'(https://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', html)
            if m:
                play = m.group(1).replace("\\/", "/")

        remark = " · ".join([x for x in [dur, (" / ".join(tags[:3]))] if x])
        content = " ".join([x for x in [desc, ("演员: " + "、".join(actors)) if actors else ""] if x])
        item = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remark,
            "vod_content": content,
            "vod_play_from": "XOJAV",
            "vod_play_url": ("正片$" + play) if play else ("正片$" + url),
        }
        return item

    @staticmethod
    def _meta(html, prop):
        m = re.search(r'<meta property="%s" content="([^"]*)"' % re.escape(prop), html)
        if m:
            return _html.unescape(m.group(1))
        m = re.search(r'<meta name="%s" content="([^"]*)"' % re.escape(prop), html)
        return _html.unescape(m.group(1)) if m else ""

    # ---------- TVBox 六方法 ----------
    def homeContent(self, filter):
        classes = [{"type_id": t, "type_name": n} for t, n in CATS]
        rows = []
        try:
            rows = self._rows(self._get(BASE + "/latest-updates"))
        except Exception:
            pass
        return {"class": classes, "filters": {}, "list": rows}

    def homeVideoContent(self):
        try:
            return {"list": self._rows(self._get(BASE + "/latest-updates"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        path = tid if tid else "latest-updates"
        if not path.startswith("categories/") and path not in ("latest-updates", "hot"):
            path = "latest-updates"
        rows = []
        if str(pg) in ("1", "", "0"):
            try:
                rows = self._rows(self._get("%s/%s" % (BASE, path)))
            except Exception:
                rows = []
        return {"list": rows, "page": 1, "pagecount": 1, "limit": 24, "total": len(rows)}

    def searchContent(self, key, quick, pg="1"):
        rows = []
        if str(pg) in ("1", "", "0"):
            try:
                rows = self._rows(self._get("%s/?s=%s" % (BASE, urllib.parse.quote(key))))
            except Exception:
                rows = []
        return {"list": rows, "page": 1, "pagecount": 1, "limit": 24, "total": len(rows)}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) else ids
        vid = str(vid).rstrip("/").split("/")[-1]
        try:
            return {"list": [self._detail(vid)]}
        except Exception as e:
            return {"list": [{"vod_id": vid, "vod_name": "[XOJAV] %s" % e,
                              "vod_play_from": "XOJAV", "vod_play_url": "正片$"} ]}

    def playerContent(self, flag, id, vipFlags):
        return {"parse": 0, "playUrl": "", "url": id,
                "header": {"User-Agent": UA, "Referer": BASE + "/"}}
