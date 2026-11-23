# -*- coding: utf-8 -*-
# TVBox / CatVodSpider Python 源 for sexkbj.com
# 依赖：仅 requests（电视盒子自带）。不需要本机网关、不需要浏览器、不需要 node。
#
# 站点结构（2026-11-23 实测）：
#   列表  WordPress REST  /wp-json/wp/v2/posts?_fields=id,date,link,title,featured_media
#   封面  /wp-json/wp/v2/media?include=<id,id,...>   一次批量取 20 张
#   分类  /wp-json/wp/v2/categories
#   详情  文章页里有大写 <IFRAME SRC="https://sexkbj.top/embed/<hash>">
#   播放  embed 页内 JS 被 Dean Edwards packer 包住，解包得 links.hls4 = m3u8（36h token）

import json
import re
import time
from urllib.parse import quote

import requests

BASE = "https://sexkbj.com"
EMBED_HOST = "https://sexkbj.top"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PAGE_SIZE = 20
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/json,*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}
FIELDS = "id,date,link,title,excerpt,featured_media"

# ------------------------------------------------------------ packer ---------
ALPHA = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _unbase(c, a):
    """复刻 JS 里的 e(c)：把序号 c 按 a 进制转成 packer 用的记号。"""
    if c < a:
        return ALPHA[c] if c < 36 else chr(c + 29)
    tail = chr(c % a + 29) if c % a > 35 else ALPHA[c % a]
    return _unbase(c // a, a) + tail


def find_packer(html):
    """从 HTML 里抠出 eval(function(p,a,c,k,e,d){...}(...)) 的整段。"""
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
    if not src:
        return ""
    m = re.match(r"^function\s*\(p,a,c,k,e,d\)\s*\{(.*)\}\((.*)\)$", src, re.S)
    if not m:
        return ""
    parts = _tokens(m.group(2))
    if len(parts) < 4:
        return ""
    try:
        p = parts[0][1].encode().decode("unicode_escape")
        a = int(parts[1][1])
        c = int(parts[2][1])
    except Exception:
        return ""
    k = parts[3][1].split("|")
    for i in range(min(c, len(k)) - 1, -1, -1):
        if k[i]:
            p = re.sub(r"\b" + re.escape(_unbase(i, a)) + r"\b", lambda _m, v=k[i]: v, p)
    return p


def grab_m3u8(js):
    m = re.findall(r"https?://[^\"'\s\\]+?\.m3u8[^\"'\s\\]*", js or "")
    for u in m:
        if "_n/master.m3u8" in u:
            return u
    return m[0] if m else ""


def grab_mp4(js):
    m = re.findall(r"https?://[^\"'\s\\]+?\.mp4[^\"'\s\\]*", js or "")
    return m[0] if m else ""


# ------------------------------------------------------------- spider --------
class Spider(object):
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.timeout = 12
        self._cats = None

    def init(self, extend=""):
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        return None

    # ---- helpers ---------------------------------------------------
    def _get(self, url, referer=None, timeout=None):
        h = {}
        if referer:
            h["Referer"] = referer
        return self.s.get(url, headers=h, timeout=timeout or self.timeout)

    def _json(self, url):
        r = self._get(url)
        if r.status_code != 200:
            raise RuntimeError("http %d" % r.status_code)
        txt = r.text.lstrip("\ufeff").strip()
        return json.loads(txt), r.headers

    def _categories(self):
        if self._cats is not None:
            return self._cats
        out = []
        try:
            data, _ = self._json(BASE + "/wp-json/wp/v2/categories"
                                        "?per_page=100&_fields=id,name,slug,count")
            for c in data:
                if not c.get("count"):
                    continue
                out.append({"type_id": str(c["id"]),
                            "type_name": c.get("name") or c.get("slug") or str(c["id"]),
                            "type_flag": "1"})
        except Exception:
            pass
        self._cats = out
        return out

    def _posts_url(self, tid, pg):
        pg = max(1, int(pg or 1))
        base = ("%s/wp-json/wp/v2/posts?per_page=%d&page=%d&_fields=%s"
                % (BASE, PAGE_SIZE, pg, FIELDS))
        t = str(tid)
        if t in ("", "latest", "new", "0"):
            return base
        if t.isdigit():
            return base + "&categories=" + t
        try:
            data, _ = self._json("%s/wp-json/wp/v2/categories?slug=%s&_fields=id"
                                 % (BASE, quote(t)))
            if data:
                return base + "&categories=%d" % data[0]["id"]
        except Exception:
            pass
        return base

    def _pics(self, items):
        """一次批量把 featured_media 换成真实图片 URL。"""
        ids = [str(i.get("featured_media") or 0) for i in items]
        ids = [x for x in ids if x and x != "0"]
        if not ids:
            return {}
        try:
            data, _ = self._json("%s/wp-json/wp/v2/media?include=%s&per_page=100&_fields=id,source_url"
                                 % (BASE, ",".join(ids)))
            return {str(m["id"]): (m.get("source_url") or "") for m in data}
        except Exception:
            return {}

    @staticmethod
    def _text(html):
        if not html:
            return ""
        t = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
        t = re.sub(r"<[^>]+>", " ", t)
        for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&quot;", '"'), ("&#8217;", "'"),
                     ("&#039;", "'"), ("&lt;", "<"), ("&gt;", ">"), ("&#8211;", "-")):
            t = t.replace(a, b)
        return re.sub(r"\s+", " ", t).strip()

    def _vod(self, item, pics):
        title = self._text((item.get("title") or {}).get("rendered", ""))
        title = re.sub(r"[_\s]*sexkbj\s*$", "", title, flags=re.I).strip()
        date = (item.get("date") or "")[:10]
        return {
            "vod_id": str(item.get("id")),
            "vod_name": title,
            "vod_pic": pics.get(str(item.get("featured_media") or ""), ""),
            "vod_remarks": date,
            "vod_year": date[:4],
            "vod_content": self._text((item.get("excerpt") or {}).get("rendered", "")),
        }

    def _listing(self, url, pg):
        data, hd = self._json(url)
        pics = self._pics(data)
        rows = [self._vod(x, pics) for x in data]
        try:
            total_pages = int(hd.get("X-WP-TotalPages") or 1)
        except Exception:
            total_pages = 1
        try:
            total = int(hd.get("X-WP-Total") or 0)
        except Exception:
            total = 0
        return {"list": rows, "page": int(pg), "pagecount": max(1, total_pages),
                "limit": PAGE_SIZE, "total": total}

    # ---- 六个方法 ---------------------------------------------------
    def homeContent(self, filter=True):
        return {"class": self._categories(), "filters": {}, "list": []}

    def homeVideoContent(self):
        try:
            return {"list": self._listing(self._posts_url("latest", 1), 1)["list"]}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter=False, extend=""):
        try:
            return self._listing(self._posts_url(tid, pg), pg)
        except Exception as e:
            return {"list": [], "page": int(pg), "pagecount": 1, "limit": PAGE_SIZE,
                    "total": 0, "msg": str(e)[:60]}

    def searchContent(self, key, quick=False, pg="1"):
        pg = max(1, int(pg or 1))
        url = ("%s/wp-json/wp/v2/posts?per_page=%d&page=%d&search=%s&_fields=%s"
               % (BASE, PAGE_SIZE, pg, quote(key), FIELDS))
        try:
            return self._listing(url, pg)
        except Exception:
            return {"list": [], "page": pg, "pagecount": 1, "limit": PAGE_SIZE, "total": 0}

    def detailContent(self, ids):
        vod_id = str(ids[0]) if isinstance(ids, (list, tuple)) else str(ids)
        out = {"vod_id": vod_id, "vod_name": "", "vod_pic": "", "vod_content": "",
               "vod_play_from": "sexkbj", "vod_play_url": ""}
        try:
            data, _ = self._json("%s/wp-json/wp/v2/posts/%s?_fields=%s,content"
                                 % (BASE, vod_id, FIELDS))
        except Exception as e:
            out["vod_content"] = "取详情失败: " + str(e)[:80]
            return {"list": [out]}

        title = self._text((data.get("title") or {}).get("rendered", ""))
        title = re.sub(r"[_\s]*sexkbj\s*$", "", title, flags=re.I).strip()
        link = data.get("link") or ("%s/?p=%s" % (BASE, vod_id))
        date = (data.get("date") or "")[:10]
        pics = self._pics([data])
        pic = pics.get(str(data.get("featured_media") or ""), "")
        text = self._text((data.get("excerpt") or {}).get("rendered", ""))

        plays = []
        try:
            html = self._get(link).text
            if not pic:
                p = re.search(r'<meta[^>]+(?:og:image|itemprop="thumbnailUrl")[^>]+content="([^"]+)"',
                              html, re.I)
                if p:
                    pic = p.group(1)
            m = re.search(r"https://sexkbj\.top/embed/[A-Za-z0-9_\-]+", html, re.I)
            if m:
                embed = m.group(0)
                ehtml = self._get(embed, referer=link).text
                js = unpack(find_packer(ehtml))
                url = self._pick_alive(js)
                if url:
                    plays.append("线路1$" + url)
                else:
                    text = (text + " | 该片所有线路都连不上（片源挂了，换一部）").strip()
            else:
                text = (text + " | 该片没有内嵌播放器").strip()
        except Exception as e:
            text = (text + " | 解析失败: " + str(e)[:60]).strip()

        out.update({"vod_name": title, "vod_pic": pic, "vod_content": text,
                    "vod_year": date[:4], "vod_remarks": date,
                    "vod_play_url": "#".join(plays)})
        return {"list": [out]}

    def _pick_alive(self, js):
        """解包后的 JS 里可能有 hls4/hls3/hls2 多条线路，挑第一条真能取到播放列表的。"""
        cands = []
        for u in re.findall(r"https?://[^\"'\s\\]+?\.m3u8[^\"'\s\\]*", js or ""):
            if u not in cands:
                cands.append(u)
        for u in re.findall(r"https?://[^\"'\s\\]+?\.mp4[^\"'\s\\]*", js or ""):
            if u not in cands:
                cands.append(u)
        if not cands:
            return ""
        cands.sort(key=lambda x: 0 if "_n/master.m3u8" in x else 1)
        for u in cands[:4]:
            try:
                r = self._get(u, referer=EMBED_HOST + "/", timeout=8)
                if r.status_code < 400 and (".m3u8" not in u or r.text.lstrip().startswith("#EXTM3U")):
                    return u
            except Exception:
                continue
        return ""

    def playerContent(self, flag, id, vipFlags=None):
        url = id
        header = {"User-Agent": UA, "Referer": EMBED_HOST + "/"}
        if isinstance(url, str) and url.startswith("sb://"):
            try:
                r = self._get(EMBED_HOST + "/embed/" + url[5:], referer=BASE + "/")
                url = grab_m3u8(unpack(find_packer(r.text))) or url
            except Exception:
                pass
        return {"parse": 0, "playUrl": "", "url": url, "header": header,
                "jx": 0, "time": int(time.time())}


# ---------------------------------------------------------- self test -------
if __name__ == "__main__":
    sp = Spider()
    sp.init("")
    t0 = time.time()
    hc = sp.homeContent()
    print("homeContent %d 类 %.2fs:" % (len(hc["class"]), time.time() - t0),
          [(c["type_name"], c["type_id"]) for c in hc["class"]])

    t0 = time.time()
    hv = sp.homeVideoContent()["list"]
    print("homeVideoContent %d 条 %.2fs" % (len(hv), time.time() - t0))
    for v in hv[:3]:
        print("   ", v["vod_id"], v["vod_name"][:44], "|", v["vod_pic"][-40:])

    tid = hc["class"][0]["type_id"]
    t0 = time.time()
    cc = sp.categoryContent(tid, 1)
    print("categoryContent tid=%s items=%d page=%s pagecount=%s total=%s %.2fs"
          % (tid, len(cc["list"]), cc.get("page"), cc.get("pagecount"),
             cc.get("total"), time.time() - t0))

    t0 = time.time()
    sc = sp.searchContent("KBJ", False, "1")
    print("searchContent items=%d %.2fs" % (len(sc["list"]), time.time() - t0))

    for vid in [hv[0]["vod_id"], cc["list"][0]["vod_id"]]:
        t0 = time.time()
        dt = sp.detailContent([vid])["list"][0]
        play = dt["vod_play_url"]
        print("detailContent #%s %.2fs play=%s" % (vid, time.time() - t0, play[:80] or "-"))
        if play:
            u = play.split("$", 1)[1]
            r = sp._get(u, referer=EMBED_HOST + "/")
            print("   m3u8:", r.status_code, len(r.content), "bytes",
                  "first:", r.text.splitlines()[0][:40])
            pc = sp.playerContent("sexkbj", u)
            print("   playerContent parse=%s len(url)=%d" % (pc["parse"], len(pc["url"])))
