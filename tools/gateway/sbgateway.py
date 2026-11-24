#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SpankBang -> TVBox gateway (local, Windows)

Why: spankbang.com sits behind a Cloudflare managed challenge
     (`Cf-Mitigated: challenge`). No UA / TLS fingerprint gets through it,
     headless Chrome does not either. A real (headful) Chrome does solve it,
     so this gateway drives a headful Chrome over CDP, renders the page,
     parses the DOM, and serves a MacCMS-compatible JSON API for TVBox.

Usage:
    python sbgateway.py                 # 0.0.0.0:8080
    python sbgateway.py --port 9000
    python sbgateway.py --headless      # challenge will most likely fail; debug only

TVBox site entry:
    { "key": "spankbang-lan", "name": "SpankBang[gateway]", "type": 1,
      "api": "http://192.168.x.x:8080/api.php/provide/vod/",
      "searchable": 1, "quickSearch": 1 }
"""
import argparse
import atexit
import html as htmlmod
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import websocket
except ImportError:
    print("missing websocket-client:  pip install websocket-client")
    sys.exit(1)

SITE = "https://spankbang.com"

CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

# (type_id, type_name, list path)
CATS = [
    ("new", "New", "/new_videos/"),
    ("trending", "Trending", "/trending_videos/"),
    ("popular", "Most Viewed", "/most_popular/"),
    ("upcoming", "Upcoming", "/upcoming/"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# 在页面里先把 HTML 剪掉无关部分再回传（见 Browser.fetch_slim 的注释）。
# 每段都是 JS 函数体，入参 t 是整页 HTML，return 一个字符串。
SLIM_JS = {
    "list": """
const re = /x-data="videoList"/gi;
const starts = []; let m;
while ((m = re.exec(t))) starts.push(Math.max(0, t.lastIndexOf('<div', m.index)));
if (!starts.length) return t;
const spans = starts.map((s, i) => [s, i + 1 < starts.length ? starts[i + 1] : t.length]);
const last = spans[spans.length - 1];
const tailText = t.slice(last[0]);
let cut = tailText.length;
for (const pat of ['<footer', 'data-testid="pagination"', 'data-testid="page-']) {
  const j = tailText.indexOf(pat);
  if (j > 0 && j < cut) cut = j;
}
last[1] = last[0] + cut;
let best = spans[0], bestN = -1;
for (const sp of spans) {
  const n = (t.slice(sp[0], sp[1]).match(/data-testid="video-item"/gi) || []).length;
  if (n > bestN) { bestN = n; best = sp; }
}
let s = t.slice(best[0], best[1]);
s = s.replace(/<script[\\s\\S]*?<\\/script>/gi, '').replace(/<style[\\s\\S]*?<\\/style>/gi, '');
s = s.replace(/\\sclass="[^"]*"/gi, '').replace(/\\sstyle="[^"]*"/gi, '');
s = s.replace(/\\ssrcset="[^"]*"/gi, '');
s = s.replace(/\\sdata-[a-z-]+="[^"]*"/gi, (x) => (/data-testid|data-id/.test(x) ? x : ''));
return s;
""",
    "detail": """
const h1m = t.match(/<h1[^>]*>([\\s\\S]*?)<\\/h1>/i);
const h1 = h1m ? h1m[1] : '';
const metas = [];
const mre = /<meta[^>]+>/gi; let mm;
while ((mm = mre.exec(t))) {
  if (/og:image|og:title|keywords|description/i.test(mm[0])) metas.push(mm[0]);
}
const links = [];
const lre = /https:\\/\\/(?:vdownload-\\d+|hls-[a-z0-9-]+)\\.sb-cd\\.com\\/[^"'\\s\\\\<>]+/g;
let lm;
while ((lm = lre.exec(t))) links.push(lm[0].replace(/&amp;/g, '&'));
return '<html><head>' + metas.join('\\n') + '</head><body><h1>' + h1 + '</h1>' +
       links.map((u) => '<a href="' + u + '">x</a>').join('') + '</body></html>';
""",
}

# 站内标签页是 /s/<tag>/，空格写成 +
# 顺序 = TVBox 筛选条里的显示顺序：中文/日文站内标签 → 日本/JAV → 直播网黄 → 通用
TAGS = [
    ("全部", ""),
    # ---- 中文 / 日文站内标签（站点自己收录的 CJK 搜索词，已逐条验证有片）----
    ("中文", "chinese"),
    ("素人自拍", "素人+自拍"),
    ("无码", "無修正"),
    ("无码(简)", "无码"),
    ("日本人无码", "日本人無修正"),
    ("巨乳人妻", "巨乳+人妻"),
    ("美熟女", "美熟女"),
    ("五十路", "五十路"),
    ("痴女", "痴女"),
    ("女教师", "女教師"),
    ("清纯", "清純"),
    ("着エロ", "着エロ"),
    ("可爱い", "可愛い"),
    ("写真偶像", "イメージビデオ"),
    ("身材出众", "スタイル抜群"),
    ("素人(日)", "しろうと"),
    ("日本人(日)", "にほんじん"),
    ("清扫口交", "お掃除フェラ"),
    ("手交", "手コキ"),
    ("假阳具", "ディルド"),
    ("受孕", "孕ませ"),
    ("原神COS", "原神"),
    ("高画质", "高画質"),
    # ---- 日本 / JAV ----
    ("日本", "japanese"),
    ("JAV", "jav"),
    ("JAV无码", "jav+uncensored"),
    ("日本无码", "japanese+uncensored"),
    ("日本人妻", "japanese+wife"),
    ("日本女女", "japanese+lesbian"),
    ("日本业余", "japanese+amateur"),
    ("日本巨乳", "japanese+big+tits"),
    ("日本内射", "japanese+creampie"),
    ("日本按摩", "japanese+massage"),
    ("日本JAV", "japanese+jav"),
    ("日本亚洲", "japanese+asian"),
    ("日本口交", "japanese+blowjob"),
    ("日本后入", "japanese+doggy"),
    ("日本硬核", "japanese+hardcore"),
    ("日本舔", "japanese+licking"),
    ("日本传教", "japanese+missonary"),
    ("日本牛仔", "japanese+cowgirl"),
    # ---- 东南亚（印尼 / 马来西亚，已逐条验证有片）----
    ("印尼", "indonesian"),
    ("印尼业余", "indonesian+amateur"),
    ("印尼熟女", "indonesian+milf"),
    ("印尼内射", "indonesian+creampie"),
    ("马来西亚", "malaysian"),
    ("马来", "malay"),
    ("马来业余", "malaysian+amateur"),
    ("马来少女", "malay+teen"),
    # ---- 孕产 ----
    ("怀孕", "pregnant"),
    ("孕妇性爱", "pregnant+sex"),
    ("孕妇内射", "pregnant+creampie"),
    ("孕妇大肚", "pregnant+belly"),
    ("孕妇肛", "pregnant+anal"),
    ("孕妇牛仔", "pregnant+cowgirl"),
    ("孕妇硬核", "pregnant+hardcore"),
    ("孕妇业余", "pregnant+amateur"),
    ("孕妇熟女", "pregnant+milf"),
    ("孕晚期", "9+months+pregnant"),
    ("妊娠", "pregnancy"),
    ("播种", "impregnation"),
    ("哺乳", "lactation"),
    ("泌乳", "milking"),
    ("繁殖", "breeding"),
    # ---- Camgirl / 网黄 ----
    ("Camgirl", "camgirl"),
    ("中文Camgirl", "chinese+camgirl"),
    ("日本Camgirl", "japanese+camgirl"),
    ("韩国Camgirl", "korean+camgirl"),
    ("亚洲Camgirl", "asian+camgirl"),
    ("Cam Girl", "cam+girl"),
    ("Cam Model", "cam+model"),
    ("Webcam", "webcam"),
    ("Chaturbate", "chaturbate"),
    ("OnlyFans", "onlyfans"),
    ("业余Cam", "amateur+cam"),
    ("Live Cam", "live+cam"),
    ("偷拍Cam", "spy+cam"),
    ("Cam2Cam", "cam2cam"),
    # ---- 通用 ----
    ("口交", "blowjob"), ("牛仔", "cowgirl"), ("后入", "doggy"),
    ("传教", "missionar"), ("一对一", "one+on+one"), ("舔", "licking"),
    ("大屌", "big+cock"), ("剃毛", "shaved+pussy"), ("硬核", "hardcore"),
    ("大鸡巴", "big+dick"), ("内射", "creampie"), ("肛", "anal"),
    ("3P", "threesome"), ("少女", "teen"), ("熟女", "milf"),
    ("业余", "amateur"), ("自拍", "homemade"), ("亚洲", "asian"),
    ("黑人", "ebony"), ("拉丁", "latina"), ("韩国", "korean"),
    ("印度", "indian"), ("潮吹", "squirt"), ("颜射", "facial"),
    ("口爆", "cumshot"), ("深喉", "deepthroat"), ("指交", "fingering"),
    ("自慰", "masturbation"), ("娇小", "petite"), ("巨乳", "busty"),
    ("跨种族", "interracial"), ("户外", "outdoor"), ("第一人称", "pov"),
    ("单人", "solo"), ("丝袜", "stockings"), ("情趣内衣", "lingerie"),
    ("群交", "gangbang"), ("双插", "double+penetration"), ("足", "feet"),
    ("按摩", "massage"), ("按摩手活", "massage+handjob"),
    ("按摩爽收", "massage+happy+ending"), ("按摩店", "massage+parlor"),
    ("女女接吻", "lesbian+kissing"), ("女女道具", "lesbian+strapon"),
    ("熟女女女", "lesbian+milf"), ("人妻", "mature"), ("BBW", "bbw"),
    ("VR", "vr"), ("JOI", "joi"), ("Hentai", "hentai"),
    ("公开", "public"), ("合集", "compilation"), ("多人群", "groupsex"),
    ("乱交", "orgy"), ("继母", "stepmom"), ("18岁", "teen+18"),
    ("尤物", "babe"),
]

# 排序：站内 /s/ 与分类页都认 ?o= 参数（new=最新，top=最热）
SORTS = [("", "默认"), ("new", "最新发布"), ("top", "最热")]

# 站点没有「日期区间」参数，但 /new_videos/ 本身就是倒序，
# 所以用「取前 N 页」近似最近 N 天（每页 72 条）。
DATES = [("1", "全部"), ("2", "最近约 1 天"), ("3", "最近约 2 天"), ("4", "最近约 3 天")]


# --------------------------------------------------------------- DNS
def resolve_via_doh(host):
    """Local DNS for spankbang.com is poisoned (175.139.142.25 blackhole).
    Ask Cloudflare DoH for the real Cloudflare edge IP instead."""
    try:
        req = urllib.request.Request(
            "https://cloudflare-dns.com/dns-query?name=%s&type=A" % host,
            headers={"accept": "application/dns-json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.load(r)
        ips = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
        if ips:
            return ips
    except Exception:
        pass
    try:
        return [socket.gethostbyname(host)]
    except Exception:
        return []


# --------------------------------------------------------------- browser
class Browser:
    def __init__(self, port=9335, headless=False):
        self.port = port
        self.headless = headless
        self.proc = None
        self.ws = None
        self.lock = threading.RLock()
        self._msg_id = 1000
        self.profile = os.path.join(os.environ.get("TEMP", "."), "sb-gateway-profile")
        self.cache = {}
        self.ttl = 300.0
        self.last_used = time.time()      # 闲置多久了，看这个
        self.stopped_for_idle = False     # 上一次是因为闲置被关掉的
        self.busy = 0                     # 正在渲染的请求数；>0 时绝不允许闲置关机
        self.ready_origin = False         # 标签页是否已经停在同源静默页（robots.txt）上
        self.warm_done = threading.Event()
        self.restart_lock = threading.Lock()

    def _chrome(self):
        for p in CHROME_CANDIDATES:
            if os.path.isfile(p):
                return p
        raise RuntimeError("chrome.exe not found")

    def start(self):
        # 先看有没有已经在跑的调试端口：多个网关实例共用同一个 profile 时，
        # Chrome 单例会把新进程并进旧浏览器，再去连一条已死的 socket（实测 10054）。
        if self._attach():
            return
        ips = resolve_via_doh("spankbang.com") + resolve_via_doh("www.spankbang.com")
        rules = []
        if ips:
            rules = ["MAP spankbang.com %s" % ips[0],
                     "MAP www.spankbang.com %s" % ips[-1]]
            print("[dns] spankbang.com -> %s" % ips)
        else:
            print("[dns] DoH failed, Chrome will use the poisoned system DNS")

        args = [
            self._chrome(),
            "--remote-debugging-port=%d" % self.port,
            "--user-data-dir=%s" % self.profile,
            "--no-first-run", "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-timer-throttling",
            "--disable-renderer-backgrounding",
            "--disable-backgrounding-occluded-windows",
            "--disable-features=CalculateNativeWinOcclusion",
            "--window-size=1280,900", "--window-position=-2400,-2400",
            "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
            "about:blank",
        ]
        if rules:
            args.insert(1, "--host-resolver-rules=%s" % ", ".join(rules))
        if self.headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)

        ws_url = None
        for _ in range(60):
            try:
                with urllib.request.urlopen(
                        "http://127.0.0.1:%d/json/list" % self.port, timeout=2) as r:
                    for t in json.load(r):
                        if t.get("type") == "page":
                            ws_url = t["webSocketDebuggerUrl"]
                            break
                if ws_url:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not ws_url:
            raise RuntimeError("chrome debug port did not come up")
        self.ws = websocket.create_connection(ws_url, timeout=120)
        self._call("Runtime.enable")
        self._call("Page.enable")
        self._block_heavy()
        self._hide_window()
        print("[chrome] ready on port %d" % self.port)

    def _hide_window(self):
        """把网关自己的 Chrome 窗口藏起来（任务栏和 Alt+Tab 都看不到）。

        必须用有头 Chrome 才能过 Cloudflare，但有头就会多一个窗口。
        这里用 Win32 ShowWindow(SW_HIDE)：窗口还在、渲染照跑，只是不显示；
        配合 --disable-backgrounding-occluded-windows，隐藏后不会被降频。
        """
        if os.name != "nt" or not getattr(self, "proc", None):
            return
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            pid = self.proc.pid
            found = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def enum_cb(hwnd, _lparam):
                wpid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
                if wpid.value == pid:
                    buf = ctypes.create_unicode_buffer(128)
                    user32.GetClassNameW(hwnd, buf, 128)
                    if buf.value.startswith("Chrome_WidgetWin"):
                        found.append(hwnd)
                return True

            user32.EnumWindows(enum_cb, 0)

            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            SW_HIDE = 0
            SWP_NOSIZE, SWP_NOZORDER, SWP_NOACTIVATE = 0x0001, 0x0004, 0x0010
            for h in found:
                ex = user32.GetWindowLongW(h, GWL_EXSTYLE)
                ex = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
                user32.SetWindowLongW(h, GWL_EXSTYLE, ex)
                user32.SetWindowPos(h, 0, -2400, -2400, 0, 0,
                                    SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
                user32.ShowWindow(h, SW_HIDE)   # SW_HIDE
            if found:
                # 改 ex-style 后要再藏一次才生效（任务栏图标才会消失）
                for h in found:
                    user32.ShowWindow(h, SW_HIDE)
            print("[chrome] window hidden (%d)" % len(found))
        except Exception as e:
            print("[chrome] hide window failed: %s" % e)

    # 图片/视频/字体/广告对解析毫无用处，但占了页面 90% 的加载时间。
    # 禁掉之后视频详情页从 ~37 秒降到几秒（实测）。
    BLOCK_URLS = [
        "*.jpg*", "*.jpeg*", "*.png*", "*.webp*", "*.avif*", "*.gif*", "*.svg*",
        "*.woff*", "*.ttf*", "*.otf*",
        "*.mp4*", "*.m3u8*", "*.ts?*",
        "*doubleclick*", "*googlesyndication*", "*google-analytics*",
        "*exoclick*", "*juicyads*", "*trafficjunky*", "*popads*", "*adnium*",
    ]

    def _block_heavy(self):
        try:
            self._call("Network.enable")
            self._call("Network.setBlockedURLs", {"urls": self.BLOCK_URLS})
        except Exception as e:
            print("[chrome] block rules failed: %s" % e)

    def _attach(self):
        """复用已经开着的调试端口（同 profile 的第二个实例会遇到这种情况）。"""
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % self.port,
                                        timeout=2) as r:
                targets = json.load(r)
        except Exception:
            return False
        for t in targets:
            if t.get("type") != "page":
                continue
            try:
                self.ws = websocket.create_connection(t["webSocketDebuggerUrl"], timeout=60)
                self._call("Runtime.enable")
                self._call("Page.enable")
                self._block_heavy()
                print("[chrome] attached to existing browser on port %d" % self.port)
                return self.alive()
            except Exception:
                return False
        return False

    def alive(self):
        try:
            with self.lock:
                self._msg_id += 1
                mid = self._msg_id
                self.ws.send(json.dumps({"id": mid, "method": "Browser.getVersion"}))
                deadline = time.time() + 4
                while time.time() < deadline:
                    raw = self.ws.recv()
                    if '"id"' not in raw:
                        continue
                    msg = json.loads(raw)
                    if msg.get("id") == mid:
                        return True
            return False
        except Exception:
            return False

    def ensure(self):
        """CDP 连接断了就重开浏览器，而不是让每个请求空转 45 秒后返回空列表。"""
        if self.alive():
            return
        with self.restart_lock:
            if self.alive():          # 别的线程已经修好了
                return
            print("[chrome] connection lost -> restarting")
            try:
                if self.ws:
                    self.ws.close()
            except Exception:
                pass
            self.ws = None
            if self.proc and self.proc.poll() is None:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
            time.sleep(2.0)
            self.start()

    def stop(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if self.proc:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.ws = None
        self.proc = None
        self.ready_origin = False

    def stop_idle(self, idle_s):
        """闲置太久：把 Chrome 关掉，把内存还回去。下一个请求会重新拉起来。"""
        print("[idle] %.0f 秒没有请求，关掉 Chrome 释放内存" % idle_s)
        self.stop()
        self.stopped_for_idle = True
        time.sleep(0.5)

    def _call(self, method, params=None, timeout=120):
        with self.lock:
            self._msg_id += 1
            mid = self._msg_id
            self.ws.send(json.dumps({"id": mid, "method": method,
                                     "params": params or {}}))
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    raw = self.ws.recv()
                except Exception:
                    return None
                # Page/Network/Runtime 的**事件**帧不带 "id"，一条 evaluate 期间能涌进来
                # 几千条；不先做这个便宜的字符串判断，光 json.loads 就要几秒
                # （实测 evaluate 本身 0.5 秒，回到 Python 却要 3 秒）。
                if '"id"' not in raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("id") == mid:
                    return msg.get("result")
            return None

    def _js(self, expr, timeout=60):
        r = self._call("Runtime.evaluate",
                       {"expression": expr, "returnByValue": True}, timeout)
        if not r:
            return None
        return r.get("result", {}).get("value")

    def fetch_html(self, url, timeout_s=40):
        """在页面上下文里 fetch() 目标 HTML（不走整页渲染）。"""
        self.busy += 1
        try:
            return self._fetch_html(url, timeout_s=timeout_s)
        finally:
            self.busy -= 1
            self.last_used = time.time()

    def fetch_slim(self, url, kind="list", timeout_s=40):
        """同 fetch_html，但只把需要的那点 HTML 带回来。

        为什么要瘦身：一次 CDP evaluate 传回 618 KB 全文，光回程就要 2.5-3 秒
        （实测：50 KB = 0.55s，200 KB = 1.48s，618 KB = 3.41s），比真正抓页面
        还贵。所以让 JS 先在本页把无关部分剪掉再返回：
        - kind="list"   → 只留结果网格，去掉 script/style 与所有 class 属性
        - kind="detail" → 只留 h1、几个 meta、以及 vdownload/hls 直链
        """
        self.busy += 1
        try:
            return self._fetch_html(url, timeout_s=timeout_s, slim=kind)
        finally:
            self.busy -= 1
            self.last_used = time.time()

    def _fetch_html(self, url, timeout_s=40, slim=None):
        t_ensure = time.time()
        self.ensure()
        t_after_ensure = time.time()
        if not self.ready_origin:
            # 让标签页停在一个「同源、没有 JS」的文档上：robots.txt 被当成纯文本渲染，
            # scripts=0，fetch 的 Promise 立刻兑现。停在首页那种 37 个脚本的页面上，
            # 页面事件循环会把 fetch 的 resolve 拖后 2 秒多（实测 wall 3.0s 而
            # 页面内 performance.now() 只报 0.6s）。
            self._call("Page.navigate", {"url": SITE + "/robots.txt"})
            for _ in range(40):
                time.sleep(0.25)
                if "spankbang" in (self._js("location.host") or ""):
                    break
            self.ready_origin = True
            print("[fast] 同源静默页就绪 %s/robots.txt" % SITE)
        if slim:
            tail = ("%s" % (SLIM_JS.get(slim) or "return t;"))
            js = ("(async () => { try {"
                  " const t0 = performance.now();"
                  " const r = await fetch(%s, {credentials: 'include',"
                  "   headers: {'accept': 'text/html,application/xhtml+xml'}});"
                  " const t = await r.text();"
                  " let out = '';"
                  " try { out = (function(t){ %s })(t); } catch (e) { out = t; }"
                  " return {code: r.status, ms: Math.round(performance.now()-t0),"
                  "         len: out.length, text: out};"
                  " } catch (e) { return {code: -1, err: String(e)}; } })()"
                  % (json.dumps(url), tail))
        else:
            js = ("(async () => { try {"
                  " const t0 = performance.now();"
                  " const r = await fetch(%s, {credentials: 'include',"
                  "   headers: {'accept': 'text/html,application/xhtml+xml'}});"
                  " const t = await r.text();"
                  " return {code: r.status, ms: Math.round(performance.now()-t0),"
                  "         len: t.length, text: t};"
                  " } catch (e) { return {code: -1, err: String(e)}; } })()"
                  % json.dumps(url))
        t_before_eval = time.time()
        r = self._call("Runtime.evaluate",
                       {"expression": js, "returnByValue": True,
                        "awaitPromise": True}, timeout_s)
        t_after_eval = time.time()
        v = (r or {}).get("result", {}).get("value") or {}
        text = v.get("text") or ""
        ok = (v.get("code") == 200 and text
              and "just a moment" not in text[:3000].lower())
        print("[fast] %s code=%s %sms %d bytes | ensure=%.2f origin=%.2f eval=%.2f" %
              (url[:64], v.get("code"), v.get("ms"), len(text),
               t_after_ensure - t_ensure, t_before_eval - t_after_ensure,
               t_after_eval - t_before_eval))
        return text if ok else ""

    def get(self, url, fresh=False, max_wait=25, marker=None):
        """带「正在忙」计数：渲染期间闲置看门狗不会把 Chrome 关掉。"""
        self.busy += 1
        try:
            return self._get(url, fresh=fresh, max_wait=max_wait, marker=marker)
        finally:
            self.busy -= 1
            self.last_used = time.time()

    def _get(self, url, fresh=False, max_wait=25, marker=None):
        """Navigate and return rendered outerHTML, cached for ttl seconds.

        marker: substring that proves the target page finished loading.
        The address bar must also match the requested path, otherwise a failed
        navigation would silently return the previous page's DOM (seen once).
        """
        now = time.time()
        self.last_used = now
        if not fresh:
            hit = self.cache.get(url)
            if hit and now - hit[0] < self.ttl:
                return hit[1]
        self.ensure()
        want = re.sub(r"^https?://[^/]+", "", url).split("?")[0].rstrip("/")
        with self.lock:
            self._call("Page.navigate", {"url": "about:blank"})
            time.sleep(0.2)
            self._call("Page.navigate", {"url": url})
            self.ready_origin = False      # 页面被导航走了，下次 fetch 要重新回静默页
            t_nav = time.time()
            # 等待条件在页面内部轮询：一次 CDP 往返就等完，比外面每 0.5 秒
            # 隔着 websocket 问一遍快几倍（之前详情页要 37-70 秒就是这个原因）。
            state = self._await_ready(marker, max_wait)
            t_wait = time.time()
            html = self._js("document.documentElement ? document.documentElement.outerHTML : ''") or ""
            t_grab = time.time()
            if marker != "js-video-item":
                print("[time] %s wait=%.1fs grab=%.1fs state=%s bytes=%d"
                      % (url[:60], t_wait - t_nav, t_grab - t_wait, state, len(html)))
            low = html.lower()
            if "just a moment" in low:
                html = ""
            if html and (marker == "js-video-item" or "vdownload-" in low):
                loops = 3 if marker == "js-video-item" else 2
                for _ in range(loops):
                    self._js("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(0.5)
                more = self._js("document.documentElement ? document.documentElement.outerHTML : ''")
                html = more or html
            self.last = {"want": want, "state": state, "bytes": len(html or "")}
            self.cache[url] = (time.time(), html)
            if len(self.cache) > 300:
                for k, _ in sorted(self.cache.items(), key=lambda kv: kv[1][0])[:100]:
                    self.cache.pop(k, None)
            return html

    def _await_ready(self, marker, timeout_s):
        cond = "(document.readyState==='complete')"
        if marker:
            cond += " && (document.documentElement.outerHTML.indexOf(%s)>=0)" % json.dumps(marker)
        js = (
            "new Promise(function(res){var t0=Date.now();var id=setInterval(function(){"
            "var ok=false;try{ok=(%s);}catch(e){ok=false;}"
            "if(ok){clearInterval(id);res('ok');}"
            "else if(Date.now()-t0>%d){clearInterval(id);res('timeout');}},300);})"
            % (cond, int(timeout_s * 1000))
        )
        r = self._call("Runtime.evaluate",
                       {"expression": js, "returnByValue": True, "awaitPromise": True},
                       timeout_s + 30)
        return (r or {}).get("result", {}).get("value")


# --------------------------------------------------------------- parsing
ITEM_RE = re.compile(r'data-testid="video-item"', re.I)
LIST_RE = re.compile(r'x-data="videoList"', re.I)


def _list_slice(html):
    """Only the real results grid matters. The page also has dropdown/mega-menu
    cards carrying the same data-testid, which polluted earlier parses.

    标签页（/s/<tag>/）会同时出现两个 x-data="videoList" 网格：第一个是站内
    推广轮播（8 条，所有标签页完全一样），第二个才是这个标签的真实结果（64 条）。
    以前只截第一个网格，所以换哪个标签看到的都是同样那 8 张海报。现在按条目数
    取最大的那个网格。
    """
    spans = []
    for m in LIST_RE.finditer(html):
        start = html.rfind("<div", 0, m.start())
        spans.append([start, len(html)])
    if not spans:
        return html
    for i in range(len(spans) - 1):
        spans[i][1] = spans[i + 1][0]
    tail = html[spans[-1][0]:]
    cut = len(tail)
    for pat in ('<footer', 'data-testid="pagination"', 'data-testid="page-'):
        j = tail.find(pat)
        if 0 < j < cut:
            cut = j
    spans[-1][1] = spans[-1][0] + cut
    best = max(spans, key=lambda s: len(ITEM_RE.findall(html[s[0]:s[1]])))
    return html[best[0]:best[1]]


def _chunks(html):
    html = _list_slice(html)
    idx = [m.start() for m in ITEM_RE.finditer(html)]
    out = []
    for i, pos in enumerate(idx):
        start = html.rfind("<div", 0, pos)
        end = idx[i + 1] if i + 1 < len(idx) else min(len(html), start + 8000)
        if i + 1 < len(idx):
            end = html.rfind("<div", 0, end)
        out.append(html[start:end])
    return out


def _first(pat, s, group=1, flags=re.S):
    m = re.search(pat, s, flags)
    return m.group(group).strip() if m else ""


def parse_list(html):
    rows = []
    for chunk in _chunks(html):
        path = _first(r'href="(/[^"]+/video/[^"]+)"', chunk)
        if not path:
            continue
        title = htmlmod.unescape(_first(r'alt="([^"]*)"', chunk)).strip()
        pic = _first(r'src="(https://tbi\.sb-cd\.com[^"]+)"', chunk)
        length = _first(r'data-testid="video-item-length"[^>]*>\s*([^<]+)', chunk)
        res = _first(r'data-testid="video-item-resolution"[^>]*>\s*([^<]+)', chunk)
        views = _first(r'data-testid="views".{0,600}?md:text-body-md">\s*([^<]+)', chunk)
        if not title:
            title = urllib.parse.unquote(path.rsplit("/", 1)[-1].replace("+", " "))
        remarks = " ".join(x for x in (res or "HD", length.strip()) if x)
        if views.strip():
            remarks += " | " + views.strip()
        rows.append({"vod_id": path, "vod_name": title,
                     "vod_pic": pic, "vod_remarks": remarks})
    return rows


def best_play(html):
    """Prefer progressive mp4 (ExoPlayer-friendly), fall back to HLS master."""
    mp4s = {}
    for m in re.finditer(
            r'https://vdownload-\d+\.sb-cd\.com/[^"\'\s\\<>]+?\.mp4\?[^"\'\s\\<>]+', html):
        u = m.group(0).replace("&amp;", "&")
        q = _first(r"-(\d+p)\.mp4", u)
        if q:
            mp4s[q] = u
    hls = ""
    m = re.search(r'https://hls-[a-z0-9-]+\.sb-cd\.com/[^"\'\s\\<>]+?master\.m3u8\?[^"\'\s\\<>]+',
                  html)
    if m:
        hls = m.group(0).replace("&amp;", "&")
    lines = ["%s$%s" % (q, mp4s[q]) for q in ("1080p", "720p", "480p", "240p")
             if q in mp4s]
    if hls:
        lines.append("HLS$%s" % hls)
    return lines


def parse_detail(html, fallback_name=""):
    title = re.sub(r"<[^>]+>", "", _first(r"<h1[^>]*>(.*?)</h1>", html))
    title = htmlmod.unescape(title).strip() or fallback_name
    pic = _first(r'<meta property="og:image" content="([^"]+)"', html)
    tags = _first(r'<meta name="keywords" content="([^"]*)"', html)
    desc = _first(r'<meta name="description" content="([^"]*)"', html)
    return {
        "vod_name": title,
        "vod_pic": pic,
        "vod_content": htmlmod.unescape(desc or tags or title),
        "vod_play_from": "SpankBang",
        "vod_play_url": "#".join(best_play(html)),
    }


# --------------------------------------------------------------- urls
def resolve_tid(tid):
    """TVBox 发来的 t 可能是分类名，也可能是 1-based 序号（t=1/2/3/4），
    首页那一次甚至根本不带 t。之前只认名字，导致返回
    {"code":0,"msg":"unknown type_id: 1","list":[]} —— App 那边就一直转圈。"""
    tid = (tid or "").strip()
    for c in CATS:
        if tid == c[0]:
            return c[0]
    if tid.isdigit():
        i = int(tid)
        if 1 <= i <= len(CATS):          # TVBox: 1,2,3,...
            return CATS[i - 1][0]
        if 0 <= i < len(CATS):           # 有些 fork: 0,1,2,...
            return CATS[i][0]
    return CATS[0][0]                    # 空 / 未知 → 回落到第一类，绝不报错


def cat_url(tid, pg):
    path = dict((c[0], c[2]) for c in CATS).get(tid)
    if not path:
        return None
    pg = max(1, int(pg or 1))
    return SITE + path if pg == 1 else SITE + path + "%d/" % pg


def list_url(tid, pg, tag="", sort=""):
    """分类页 / 标签页 + 排序参数拼成最终 URL。

    标签页形如 /s/blowjob/2/?o=new；分类页形如 /new_videos/2/?o=new。
    """
    pg = max(1, int(pg or 1))
    if tag:
        # TVBox 有时把标签名里的 + 原样发过来、有时发成空格，这里统一成网址里的 + 形式
        tag = tag.strip().replace(" ", "+").replace("%20", "+")
        path = "/s/%s/" % tag
    else:
        path = dict((c[0], c[2]) for c in CATS).get(tid)
        if not path:
            return None
    url = SITE + path + ("" if pg == 1 else "%d/" % pg)
    if sort in ("new", "top"):
        url += "?o=" + sort
    return url


def build_filters():
    """TVBox 的筛选条：按分类返回可选筛选项，键名就是请求里会带回来的参数名。"""
    tags = [{"n": n, "v": v} for n, v in TAGS]
    sorts = [{"n": n, "v": v} for v, n in SORTS]
    dates = [{"n": n, "v": v} for v, n in DATES]
    one = [
        {"key": "tag", "name": "标签", "value": tags},
        {"key": "sort", "name": "排序", "value": sorts},
        {"key": "date", "name": "时间", "value": dates},
    ]
    return dict((c[0], one) for c in CATS)


# ---- 列表快照：Chrome 因闲置被关掉后，首页/首页翻页仍能立刻拿到内容，
#      不用让 App 干等 8-20 秒的冷启动。
SNAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "list_snapshot.json")
SNAP_VER = 2          # 解析规则一改就加一，旧快照整体作废（曾出现 72 条旧网格混进来）
SNAPSHOT = {}
_snap_lock = threading.Lock()
_snap_dirty = [False]


def load_snapshot():
    global SNAPSHOT
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if data.pop("__ver", 0) != SNAP_VER:
            print("[snap] 旧版快照已作废（解析规则变了）")
            SNAPSHOT = {}
            return
        SNAPSHOT = data
        print("[snap] 载入 %d 个列表快照" % len(SNAPSHOT))
    except Exception:
        SNAPSHOT = {}


def save_snapshot():
    with _snap_lock:
        if not _snap_dirty[0]:
            return
        data = dict(SNAPSHOT)
        data["__ver"] = SNAP_VER
        _snap_dirty[0] = False
    try:
        tmp = SNAP_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, SNAP_PATH)
    except Exception as e:
        print("[snap] 写入失败: %s" % e)


def note_snapshot(url, rows, limit=80):
    if not rows:
        return
    with _snap_lock:
        SNAPSHOT[url] = rows[:limit]
        _snap_dirty[0] = True


def fetch_list(browser, url, fresh=False):
    """渲染并解析列表页。先用页面内 fetch 的快速通道，失败再退回整页渲染。
    fresh 只表示「别用整页渲染的缓存」，快速通道本身一次只要半秒，照样走。"""
    try:
        fast = browser.fetch_slim(url, "list")
    except Exception as e:
        print("[fast] 列表加速失败 %s: %s" % (url[:60], e))
        fast = ""
    if fast:
        rows = parse_list(fast)
        if rows:
            note_snapshot(url, rows)
            return rows
    html = browser.get(url, fresh=fresh, marker="js-video-item")
    rows = parse_list(html)
    if not rows and not fresh:
        print("[warn] 0 items from %s (html %d bytes) -> retry" % (url, len(html or "")))
        html = browser.get(url, fresh=True, marker="js-video-item")
        rows = parse_list(html)
    if not rows:
        browser.cache.pop(url, None)
        print("[warn] 0 items from %s (html %d bytes)" % (url, len(html or "")))
    else:
        note_snapshot(url, rows)
    return rows


def warm_async(browser, url):
    """Chrome 因闲置被关掉时，先用磁盘快照顶上去，再在后台把这一页重新渲染。"""
    def run():
        try:
            fetch_list(browser, url, fresh=True)
            print("[warm] async 完成 %s" % url)
        except Exception as e:
            print("[warm] async 失败 %s: %s" % (url, e))
    threading.Thread(target=run, daemon=True).start()


def idle_watch(browser, idle_s, interval=30):
    """闲置超时就关掉 Chrome；下一个请求会走 ensure() 自动重新拉起。"""
    tick = max(5.0, min(float(interval), idle_s / 3.0))
    while True:
        try:
            time.sleep(tick)
            if idle_s <= 0:
                continue
            if browser.ws is None:            # 已经关着了
                continue
            if browser.busy:                  # 正在渲染，别动
                continue
            if not browser.warm_done.is_set():  # 预热还没跑完
                continue
            idle = time.time() - browser.last_used
            if idle >= idle_s:
                browser.stop_idle(idle)
                save_snapshot()
        except Exception as e:
            print("[idle] watcher 异常: %s" % e)

def warm_cache(browser, pages=3):
    """启动时把四个分类的前几页先抓好，TVBox 首屏和往下翻直接命中快照。
    冷启动整页渲染一次要 8-20 秒，超过 App 的读超时就会显示"一直加载"；
    现在走页面内 fetch，一页半秒左右，四个分类 × 三页也就十秒内。"""
    try:
        for c in CATS:
            for pg in range(1, pages + 1):
                url = list_url(c[0], pg)
                try:
                    rows = fetch_list(browser, url)
                    print("[warm] %-9s pg%d %d items" % (c[0], pg, len(rows)))
                except Exception as e:
                    print("[warm] %-9s pg%d failed: %s" % (c[0], pg, e))
    finally:
        browser.warm_done.set()
        browser.last_used = time.time()
        save_snapshot()
        print("[warm] done, 闲置计时从这里开始")


def search_url(kw, pg):
    pg = max(1, int(pg or 1))
    q = urllib.parse.quote_plus(kw)
    return "%s/s/%s/?o=all" % (SITE, q) if pg == 1 else "%s/s/%s/%d/?o=all" % (SITE, q, pg)


def detail_url(vod_id):
    if vod_id.startswith("http"):
        return vod_id
    return SITE + (vod_id if vod_id.startswith("/") else "/" + vod_id)


# ---- 详情缓存：TVBox 读详情页的超时很短（十秒上下），而冷渲染一次要 8–17 秒。
#      超时后 App 直接掐连接（日志里的 ConnectionAbortedError），播放器就一直转圈。
#      所以详情先查缓存；列表下发时顺手把前几条在后台渲染好，点进去就是秒开。
DETAIL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "detail_cache.json")
DETAIL = {}
_detail_lock = threading.Lock()
_detail_dirty = [False]
_detail_busy = set()
DETAIL_TTL = 3 * 3600        # 直链里的 secure=时间戳会过期，超过 3 小时就重取


def load_details():
    global DETAIL
    try:
        with open(DETAIL_PATH, encoding="utf-8") as f:
            DETAIL = json.load(f)
        print("[detail] 载入 %d 条详情缓存" % len(DETAIL))
    except Exception:
        DETAIL = {}


def save_details():
    with _detail_lock:
        if not _detail_dirty[0]:
            return
        data = dict(DETAIL)
        _detail_dirty[0] = False
    try:
        tmp = DETAIL_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, DETAIL_PATH)
    except Exception as e:
        print("[detail] 写入失败: %s" % e)


def detail_cached(browser, vod_id, force=False):
    """返回详情 dict（还没做 /play 改写）。命中缓存就不碰 Chrome。"""
    now = time.time()
    with _detail_lock:
        ent = DETAIL.get(vod_id)
        if ent and not force and now - ent.get("at", 0) < DETAIL_TTL:
            return dict(ent["data"])
    html = ""
    try:
        html = browser.fetch_slim(detail_url(vod_id), "detail")
    except Exception as e:
        print("[fast] 详情加速失败 %s: %s" % (str(vod_id)[:40], e))
    if html and "vdownload-" in html.lower():
        d = parse_detail(html)
    else:
        d = parse_detail(browser.get(detail_url(vod_id), marker="vdownload-",
                                     max_wait=60))
    d["vod_id"] = vod_id
    if not d.get("vod_play_url"):
        return d              # 抓空的不缓存，下次还能重试
    with _detail_lock:
        DETAIL[vod_id] = {"at": now, "data": d}
        _detail_dirty[0] = True
    return dict(d)


PREFETCH_LIMIT = [0]     # 后台预取条数；默认关闭（CDP evaluate 串行，预取会和翻页抢锁）


def prefetch_details(browser, vod_ids, limit=None):
    """列表下发后在后台把前几条详情抓好，用户点进去时就不用等。

    默认**不启用**（`--prefetch N` 才开）：详情走页面内 fetch 只要 0.5-2 秒，
    而 CDP 的 evaluate 是串行的，后台预取会把翻页请求挡在后面（实测拖到 4-6 秒）。
    """
    if limit is None:
        limit = PREFETCH_LIMIT[0]
    if limit <= 0 or not vod_ids:
        return

    def run():
        n = 0
        for vid in [v for v in vod_ids[:limit] if v]:
            for _ in range(20):
                if not browser.busy and time.time() - browser.last_used >= 1.2:
                    break
                time.sleep(0.3)
            else:
                print("[pre] 一直有请求，预取放弃")
                break
            with _detail_lock:
                ent = DETAIL.get(vid)
                if ent and time.time() - ent.get("at", 0) < DETAIL_TTL:
                    continue
                if vid in _detail_busy:
                    continue
                _detail_busy.add(vid)
            try:
                detail_cached(browser, vid)
                n += 1
            except Exception as e:
                print("[pre] %s 失败: %s" % (str(vid)[:40], e))
            finally:
                with _detail_lock:
                    _detail_busy.discard(vid)
            time.sleep(0.6)
        if n:
            save_details()
            print("[pre] 后台预热 %d 条详情完成" % n)

    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------- http
def make_handler(browser):
    classes = [{"type_id": c[0], "type_name": c[1]} for c in CATS]
    FILTERS = build_filters()

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *a):
            sys.stderr.write("[gw] %s %s\n" % (self.address_string(), fmt % a))

        def _send(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            try:
                self.end_headers()
                self.wfile.write(body)
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError) as e:
                # TVBox 读超时后会把连接掐掉，这不是我们的错，别打一屏 traceback
                print("[gw] 客户端提前断开（%s）: %s" % (self.path[:60], e))

        def do_GET(self):
            try:
                self.route()
            except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
                pass
            except Exception as e:
                try:
                    self._send({"code": 0, "msg": "gateway error: %s" % e,
                                "class": classes, "list": []})
                except Exception:
                    pass

        def do_HEAD(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith("/play"):
                q = urllib.parse.parse_qs(u.query)
                try:
                    self._proxy(q.get("u", [""])[0], head_only=True)
                except Exception as e:
                    print("[play] HEAD failed: %s" % e)
                return
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ---- 播放代理：盒子直接连 vdownload-*.sb-cd.com 失败时，改由网关代取。
        #      支持 Range，所以拖进度条也能用。
        def _proxy(self, url, head_only=False):
            if not url.startswith("http"):
                self._send({"code": 0, "msg": "bad url"}, 400)
                return
            req = urllib.request.Request(url, headers={
                "User-Agent": UA, "Referer": SITE + "/", "Accept": "*/*"})
            rng = self.headers.get("Range")
            if rng:
                req.add_header("Range", rng)
            self.close_connection = True
            # 播放响应按 HTTP/1.0 发：老播放器/自带 OkHttp 的拼装逻辑对
            # HTTP/1.1 + Connection: close 的组合容易走进异常分支（TVBox 会
            # 直接崩），HTTP/1.0 语义最保守，Content-Length 照样给。
            self.protocol_version = "HTTP/1.0"
            try:
                up = urllib.request.urlopen(req, timeout=40)
                code = up.getcode()
            except urllib.error.HTTPError as e:
                up, code = e, e.code
            except Exception as e:
                print("[play] upstream failed: %s (%s)" % (e, url[:70]))
                self.send_response(502)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(code)
            ctype = up.headers.get("Content-Type") or "video/mp4"
            if "m3u8" in url.lower():
                ctype = "application/vnd.apple.mpegurl"
            self.send_header("Content-Type", ctype)
            for h in ("Content-Length", "Content-Range", "Accept-Ranges",
                      "Last-Modified", "ETag"):
                v = up.headers.get(h)
                if v:
                    self.send_header(h, v)
            # 始终显式声明 Connection: close：我们按块转发完就断，
            # 不声明的话某些播放器会当成 keep-alive 提前复用连接而读崩。
            self.send_header("Connection", "close")
            self.send_header("Content-Disposition", 'inline; filename="video%s"'
                             % (".m3u8" if "m3u8" in url.lower() else ".mp4"))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            if head_only:
                print("[play] HEAD %s -> %d" % (url[:70], code))
                return
            sent = 0
            try:
                while True:
                    buf = up.read(65536)
                    if not buf:
                        break
                    self.wfile.write(buf)
                    sent += len(buf)
            except Exception as e:
                print("[play] stopped after %d bytes: %s" % (sent, e))
            print("[play] %s -> %d, %d bytes" % (url[:70], code, sent))

        def _host(self):
            return self.headers.get("Host") or "127.0.0.1:8080"

        def _proxy_urls(self, items, max_q=""):
            """把片源直链改写成经过本网关的播放地址，盒子只需要能连本机。

            路径故意带 .mp4 结尾：不少 TVBox 内核靠扩展名挑解码器，
            纯 ?u= 这种没有后缀的地址会让某些版本在 native 层直接崩。
            """
            order = ["1080p", "720p", "480p", "240p"]
            allow = set(order[order.index(max_q):]) if max_q in order else set(order)
            for it in items:
                pu = it.get("vod_play_url") or ""
                out = []
                for one in pu.split("#"):
                    one = one.strip()
                    if not one:
                        continue
                    name, _, link = one.partition("$")
                    if not link:
                        name, link = "播放", name
                    if name in order and name not in allow:
                        continue    # 站点链接带 &q=480 之类时限制最高清晰度
                    if link.startswith("http"):
                        if ".m3u8" in link.lower():
                            # HLS 的切片地址在 m3u8 里还是 CDN 域名，盒子自己去取
                            # 一样会失败；在没做播放列表改写前先不给这条，免得
                            # 播放器抢先选 HLS 然后崩。
                            continue
                        ext = ".mp4"
                        slug = re.sub(r"[^A-Za-z0-9._-]", "", name) or "video"
                        link = "http://%s/play/%s%s?u=%s" % (
                            self._host(), slug, ext, urllib.parse.quote(link, safe=""))
                    out.append("%s$%s" % (name, link))
                it["vod_play_url"] = "#".join(out)
            return items

        def route(self):
            u = urllib.parse.urlparse(self.path)
            if u.path.startswith("/play"):
                q = urllib.parse.parse_qs(u.query)
                self._proxy(q.get("u", [""])[0])
                return
            if u.path == "/_debug":
                q = urllib.parse.parse_qs(u.query)
                p = q.get("path", ["/new_videos/"])[0]
                url = p if p.startswith("http") else SITE + p
                html = browser.get(url, fresh=True, marker=None)
                low = (html or "").lower()
                links = re.findall(r'href="([^"]*(?:page|/2/|\?p=)[^"]*)"', html or "")[:12]
                self._send({"url": url, "bytes": len(html or ""),
                            "items": len(parse_list(html or "")),
                            "challenge": "just a moment" in low,
                            "last": getattr(browser, "last", None),
                            "pager_links": links})
                return
            if u.path in ("/", "/index.html"):
                self._send({"ok": True, "site": "spankbang-gateway", "via": "headful chrome cdp",
                            "api": "/api.php/provide/vod/",
                            "cats": [c[0] for c in CATS]})
                return
            if not u.path.rstrip("/").endswith("provide/vod"):
                # 允许用路径限制最高清晰度：/api.php/provide/vod/q480/
                # （TVBox 是直接拿 api 字符串拼 ?ac=...，塞在 query 里会拼坏）
                _p = u.path.rstrip("/")
                _m = re.search(r"/q(\d{3,4}p?)$", _p, re.I)
                if not _m or not _p[:_m.start()].rstrip("/").endswith("provide/vod"):
                    self._send({"code": 0, "msg": "not found",
                                "class": classes, "list": []}, 404)
                    return
                forced_q = _m.group(1).lower()
                if forced_q.isdigit():
                    forced_q += "p"
            else:
                forced_q = ""

            q = urllib.parse.parse_qs(u.query)
            ac = (q.get("ac", ["list"])[0] or "list").lower()
            tid = resolve_tid(q.get("t", [""])[0])
            pg = q.get("pg", ["1"])[0]
            wd = q.get("wd", [""])[0]
            ids = q.get("ids", [""])[0]
            want_detail = ac in ("detail", "videolist")

            def pack(items, total=None, pagecount=999):
                self._send({"code": 1, "msg": "ok", "page": int(pg or 1),
                            "pagecount": pagecount, "limit": str(len(items)),
                            "total": int(total if total is not None else len(items)),
                            "class": classes, "filters": FILTERS, "list": items})
                # 列表先发出去，再在后台把前几条详情渲染好（点进去秒开）
                if items and not ids:
                    try:
                        prefetch_details(browser, [i.get("vod_id") for i in items])
                    except Exception as e:
                        print("[pre] 启动失败: %s" % e)

            # ---- search
            if wd:
                rows = fetch_list(browser, search_url(wd, pg))
                if not rows:
                    rows = fetch_list(browser, "%s/s/%s/" % (SITE, urllib.parse.quote_plus(wd)),
                                      fresh=True)
                # 搜索也只回列表：逐条抓 20 个详情页要几分钟，TVBox 早就超时了。
                pack(rows)
                return

            # ---- detail by ids
            if want_detail and ids:
                out = []
                for one in [x for x in re.split(r"[,$$]", ids) if x.strip()]:
                    one = one.strip()
                    out.append(detail_cached(browser, one))
                maxq = q.get("q", [""])[0].strip().lower()
                if maxq.isdigit():
                    maxq += "p"          # ?q=480 与 ?q=480p 都认
                if not maxq:
                    maxq = forced_q
                pack(self._proxy_urls(out, maxq) if q.get("mode", [""])[0] != "direct" else out)
                return

            # ---- category list（带筛选：标签 / 排序 / 时间）
            # TVBox 把筛选结果打包成一个 JSON 塞进 f= 参数：
            #   ?f={"tag":"blowjob","sort":"top"}&t=new&ac=detail&pg=1
            # 所以 f 必须解析，单靠 tag=/sort= 那些独立参数是收不到的。
            fraw = (q.get("f", [""])[0] or "").strip()
            fobj = {}
            if fraw:
                try:
                    fobj = json.loads(fraw)
                except Exception:
                    print("[filter] f= 不是合法 JSON: %r" % fraw[:120])
                    fobj = {}

            def pick(key, direct):
                v = fobj.get(key)
                if isinstance(v, str) and v.strip():
                    return v.strip()
                if isinstance(v, (int, float)):
                    return str(v)
                return direct

            tag = urllib.parse.unquote(pick("tag", (q.get("tag", [""])[0] or ""))).strip()
            sort = pick("sort", (q.get("sort", [""])[0] or "")).strip()
            dsel = pick("date", (q.get("date", [""])[0] or "")).strip()
            span = int(dsel) if dsel.isdigit() else 1
            span = max(1, min(4, span))
            start = max(1, int(pg or 1))
            if fraw:
                print("[filter] tid=%s tag=%r sort=%r date=%r pg=%s"
                      % (tid, tag, sort, dsel, start))
            if not tag and not dict((c[0], c[2]) for c in CATS).get(tid):
                self._send({"code": 0, "msg": "unknown type_id: %s" % tid,
                            "class": classes, "list": []})
                return
            # ---- Chrome 因闲置被关掉时，先用磁盘快照顶上，别让 App 干等冷启动
            cold = browser.ws is None
            if cold:
                want = [list_url(tid, p, tag, sort) for p in range(start, start + span)]
                want = [u for u in want if u]
                rows, seen_ids, missing = [], set(), []
                for u in want:
                    snap = SNAPSHOT.get(u)
                    if not snap:
                        missing.append(u)
                        continue
                    for r in snap:
                        k = r.get("vod_id")
                        if k in seen_ids:
                            continue
                        seen_ids.add(k)
                        rows.append(r)
                if rows:
                    print("[snap] 命中 %d 页 / 缺 %d 页（Chrome 冷启动中）" % (len(want) - len(missing), len(missing)))
                    pack(rows, pagecount=1 if span > 1 else 999)
                    warm_async(browser, missing[0] if missing else want[0])
                    return

            rows, seen_ids = [], set()
            for p in range(start, start + span):
                u = list_url(tid, p, tag, sort)
                if not u:
                    break
                for r in fetch_list(browser, u):
                    k = r.get("vod_id")
                    if k in seen_ids:
                        continue
                    seen_ids.add(k)
                    rows.append(r)
            # 时间筛选是多页合并出来的，翻页没有意义，直接告诉 App 只有一页
            pack(rows, pagecount=1 if span > 1 else 999)

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--browser-port", type=int, default=9335)
    ap.add_argument("--headless", action="store_true")
    ap.add_argument("--log", default="", help="同时把输出写进这个文件（排错用）")
    ap.add_argument("--idle-minutes", type=float, default=10.0,
                    help="闲置多少分钟关掉 Chrome（0 = 一直开着）")
    ap.add_argument("--prefetch", type=int, default=0,
                    help="列表下发后后台预取多少条详情（默认 0，开了会拖慢翻页）")
    args = ap.parse_args()
    PREFETCH_LIMIT[0] = max(0, args.prefetch)

    # 单实例保护：已经被占用就退出（返回码 100 给 start.cmd 判断），
    # 否则两个实例会抢同一个 Chrome，日志也会两行一交错。
    import socket as _socket
    _probe = _socket.socket()
    _probe.settimeout(1.0)
    try:
        if _probe.connect_ex(("127.0.0.1", args.port)) == 0:
            print("[http] port %d already in use, another gateway is running" % args.port)
            _probe.close()
            return 100
    finally:
        try:
            _probe.close()
        except Exception:
            pass

    if args.log:
        _logf = open(args.log, "a", encoding="utf-8", buffering=1)

        class _Tee:
            def __init__(self, *streams):
                self.streams = streams

            def write(self, s):
                for st in self.streams:
                    try:
                        st.write(s)
                        st.flush()
                    except Exception:
                        pass
                return len(s)

            def flush(self):
                for st in self.streams:
                    try:
                        st.flush()
                    except Exception:
                        pass

        sys.stdout = _Tee(sys.stdout, _logf)
        sys.stderr = _Tee(sys.stderr, _logf)
        print("\n===== %s start =====" % time.strftime("%Y-%m-%d %H:%M:%S"))

    b = Browser(port=args.browser_port, headless=args.headless)
    b.start()
    load_snapshot()
    load_details()
    atexit.register(save_snapshot)
    atexit.register(save_details)
    srv = ThreadingHTTPServer((args.host, args.port), make_handler(b))
    srv.daemon_threads = True
    print("[http] http://%s:%d/api.php/provide/vod/" % (args.host, args.port))
    threading.Thread(target=warm_cache, args=(b,), daemon=True).start()
    idle_s = max(0.0, float(args.idle_minutes) * 60.0)
    if idle_s > 0:
        print("[idle] 闲置 %.0f 秒后关掉 Chrome（有请求会自动重开）" % idle_s)
        threading.Thread(target=idle_watch, args=(b, idle_s), daemon=True).start()
    else:
        print("[idle] 闲置关闭已禁用")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        b.stop()
        save_snapshot()
        save_details()

if __name__ == "__main__":
    sys.exit(main() or 0)
