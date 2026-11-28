"""erome 的本地网关（CMS 门面）。

为什么要它：电视端跑 py 爬虫时，cookie 必须写在源配置里（等于把账号抄一份到设备上），
而且电视端的 DNS 常被污染、CDN 播放还要求 Referer。这个网关把三件事都留在电脑上：

  1. 用你**已经登录过**的 Chrome 配置目录（erome_login.py 用的那个）取页面，cookie 不出这台机器；
  2. 用 Cloudflare DoH 解析真实 IP，绕开 ISP 污染；
  3. 播放地址走 /play 反向代理，自动补 Referer（CDN 裸请求是 403）。

电视端只需要一条 type=1 源：http://<本机IP>:8082/api.php/provide/vod/

用法：
    python erome_gateway.py --port 8082
    python erome_gateway.py --port 8082 --log erome-gateway.log
"""
import argparse
import json
import os
import re
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

VER = "v1.2"

SITE = "https://www.erome.com"
PROFILE = os.path.join(tempfile.gettempdir(), "erome-login-profile")
CDP_PORT = 9338
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]

CATS = [
    ("latest", "最新"),
    ("feed", "关注动态"),
    ("feed_posts", "关注·发布"),
    ("feed_reposts", "关注·转发"),
    ("liked", "我赞过的"),
    ("saved", "我的收藏"),
]

LIST_PATH = {
    "latest": "/explore?page=%d",
    "feed": "/user/feed?page=%d",
    "feed_posts": "/user/feed?t=posts&page=%d",
    "feed_reposts": "/user/feed?t=reposts&page=%d",
    "liked": "/user/liked?page=%d",
    "saved": "/user/saved?page=%d",
}

# ---------- 时长缓存（海报上显示「最长 02:31」用） ----------
DUR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "durations.json")
DUR_TTL = 7 * 24 * 3600
DUR = {}
_dur_lock = threading.Lock()
_dur_dirty = [False]
_prefetch_lock = threading.Lock()
_prefetch_running = [False]


def load_dur():
    try:
        if os.path.exists(DUR_PATH):
            with open(DUR_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                DUR.update(data)
            log("[dur] 载入 %d 个专辑时长" % len(DUR))
    except Exception as e:
        log("[dur] 载入失败: %s" % e)


def save_dur():
    if not _dur_dirty[0]:
        return
    try:
        tmp = DUR_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(DUR, f, ensure_ascii=False)
        os.replace(tmp, DUR_PATH)
        _dur_dirty[0] = False
    except Exception as e:
        log("[dur] 保存失败: %s" % e)


def secs(text):
    """'01:14' / '1:02:03' -> 秒。"""
    try:
        parts = [int(x) for x in str(text).strip().split(":")]
    except Exception:
        return 0
    total = 0
    for p in parts:
        total = total * 60 + p
    return total


def fmt_dur(s):
    s = int(s or 0)
    if s <= 0:
        return ""
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    if h:
        return "%d:%02d:%02d" % (h, m, sec)
    return "%d:%02d" % (m, sec)


def dur_info(aid):
    hit = DUR.get(aid)
    if not hit or time.time() - hit.get("t", 0) > DUR_TTL:
        return None
    return hit


def note_dur(aid, videos):
    if not aid or not videos:
        return
    ds = [secs(v.get("dur") or "") for v in videos]
    ds = [d for d in ds if d > 0]
    with _dur_lock:
        DUR[aid] = {"n": len(videos), "max": max(ds) if ds else 0,
                    "sum": sum(ds), "t": int(time.time())}
        _dur_dirty[0] = True

VIDEO_ONLY = True
MAX_PAGES = 3
CACHE_TTL = 240

_LINK_RE = re.compile(r'<a[^>]+class="album-link"[^>]+href="(https?://[^"]+/a/[A-Za-z0-9]+)"', re.S)
_IMG_RE = re.compile(r'<img[^>]+class="album-thumbnail[^"]*"[^>]+src="([^"]+)"', re.S)
_TITLE_RE = re.compile(r'<a[^>]+href="https://www\.erome\.com/a/[A-Za-z0-9]+"[^>]*>([^<]{1,200})</a>', re.S)
_USER_RE = re.compile(r'<span class="album-user"[^>]*>([^<]{1,80})</span>', re.S)
_VID_RE = re.compile(r'class="album-videos"[^>]*>.*?</svg>\s*(\d+)', re.S)
_PIC_RE = re.compile(r'class="album-images"[^>]*>.*?</svg>\s*(\d+)', re.S)
_SOURCE_RE = re.compile(r'<source[^>]+src="(https?://[^"]+?\.mp4[^"]*)"', re.S)
_H1_RE = re.compile(r'<h1[^>]*>(.*?)</h1>', re.S)

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_PRINT_LOCK = threading.Lock()


def log(*parts):
    with _PRINT_LOCK:
        print(time.strftime("[%H:%M:%S]"), *parts, flush=True)


def clean(s):
    s = re.sub(r"<[^>]+>", "", s or "")
    s = (s.replace("&amp;", "&").replace("&quot;", '"').replace("&#039;", "'")
          .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
    return re.sub(r"\s+", " ", s).strip()


def doh_ip(host):
    try:
        req = urllib.request.Request("https://1.1.1.1/dns-query?name=%s&type=A" % host,
                                     headers={"accept": "application/dns-json"})
        data = json.loads(urllib.request.urlopen(req, timeout=8, context=_CTX).read().decode())
        for ans in (data.get("Answer") or []):
            if ans.get("type") == 1 and ans.get("data"):
                return ans["data"]
    except Exception as e:
        log("[doh] failed:", e)
    return None


class Browser:
    """有头 Chrome + CDP。用登录过的 profile，页面里 fetch 拿 HTML。"""

    def __init__(self):
        self.proc = None
        self.ws = None
        self._id = 0
        self.ready_origin = False
        self.cache = {}
        # CDP 是单通道：一次只能跑一条 evaluate，多请求必须排队，否则 ws 会互相踩、偶发超时
        self.lock = threading.RLock()
        self.connect_lock = threading.Lock()
        self.last_good = {}          # path -> rows（上次成功的结果，抓取失败时顶上去）
        self.detail_cache = {}       # aid -> detail dict
        self.detail_lock = threading.Lock()
        self.detail_ttl = 1800

    # ---- 底层 ----
    def _http_json(self, path, timeout=5):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (CDP_PORT, path), timeout=timeout) as r:
            return json.loads(r.read().decode())

    def _pick_page(self):
        targets = self._http_json("/json")
        pages = [t for t in targets if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("no page target")
        # 优先挑 erome 的标签页
        for t in pages:
            if "erome" in (t.get("url") or ""):
                return t
        return pages[0]

    def start(self):
        import websocket  # noqa: F401
        if self.alive():
            # 浏览器已经在跑（例如上次的进程还在），直接挂上去，不要再起一个抢 profile
            self._connect()
            return
        chrome = next((p for p in CHROME_CANDIDATES if p and os.path.exists(p)), None)
        if not chrome:
            raise RuntimeError("chrome not found")
        ip = doh_ip("www.erome.com")
        log("[chrome] DoH www.erome.com ->", ip)
        os.makedirs(PROFILE, exist_ok=True)
        args = [chrome,
                "--remote-debugging-port=%d" % CDP_PORT,
                "--user-data-dir=%s" % PROFILE,
                "--no-first-run", "--no-default-browser-check",
                "--disable-session-crashed-bubble", "--hide-crash-restore-bubble",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--disable-features=CalculateNativeWinOcclusion",
                "--window-position=-2400,-2400",
                "--window-size=1280,900"]
        if ip:
            args.append("--host-resolver-rules=MAP www.erome.com %s" % ip)
        args.append(SITE)
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                self._pick_page()
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("chrome debug port not up")
        self._connect()

    def _connect(self):
        import websocket
        page = self._pick_page()
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=30,
                                              suppress_origin=True)
        self._hide()
        self._block()
        self.ready_origin = False
        log("[chrome] attached")

    def _call(self, method, **params):
        if self.ws is None:
            raise RuntimeError("no ws")
        with self.lock:
            self._id += 1
            mid = self._id
            self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
            end = time.time() + 90
            while time.time() < end:
                try:
                    raw = self.ws.recv()
                except Exception as e:
                    self.ws = None
                    raise RuntimeError("ws broken: %s" % e)
                if '"id"' not in raw:
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                if msg.get("id") == mid:
                    if "error" in msg:
                        raise RuntimeError(str(msg["error"])[:200])
                    return msg.get("result") or {}
            # 超时就把这条连接标记为脏，下一次调用会重连
            self.ws = None
            raise TimeoutError(method)

    def alive(self):
        try:
            return bool(self._http_json("/json/version", timeout=3))
        except Exception:
            return False

    def ensure(self):
        """ws 断了就重连；连不上就重启 Chrome。多线程下只有一个线程负责重连。"""
        if self.ws is not None and self._ws_ok():
            return
        with self.connect_lock:
            if self.ws is not None and self._ws_ok():
                return
            log("[chrome] (re)connect")
            try:
                if self.alive():
                    self._connect()          # 浏览器还活着，只重连 ws
                    return
            except Exception as e:
                log("[chrome] reconnect failed:", e)
            self.stop()
            self.start()

    def _ws_ok(self):
        try:
            self._call("Browser.getVersion")
            return True
        except Exception:
            return False

    def _hide(self):
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            SW_HIDE = 0
            GWL_EXSTYLE = -20
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_APPWINDOW = 0x00040000
            hwnds = []

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def cb(hwnd, _):
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if self.proc and pid.value == self.proc.pid:
                    cls = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, cls, 256)
                    if cls.value.startswith("Chrome_WidgetWin"):
                        hwnds.append(hwnd)
                return True

            user32.EnumWindows(cb, 0)
            for h in hwnds:
                style = user32.GetWindowLongW(h, GWL_EXSTYLE)
                user32.SetWindowLongW(h, GWL_EXSTYLE,
                                      (style | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW)
                user32.SetWindowPos(h, 0, -2400, -2400, 0, 0, 0x0001 | 0x0004)
                user32.ShowWindow(h, SW_HIDE)
            if hwnds:
                log("[chrome] window hidden (%d)" % len(hwnds))
        except Exception as e:
            log("[chrome] hide failed:", e)

    def _block(self):
        try:
            self._call("Network.enable")
            self._call("Network.setBlockedURLs", urls=[
                "*.jpg*", "*.jpeg*", "*.png*", "*.webp*", "*.gif*", "*.svg*",
                "*.woff*", "*.ttf*", "*.otf*", "*.mp4*", "*.m3u8*",
                "*doubleclick*", "*googlesyndication*", "*google-analytics*",
                "*exoclick*", "*juicyads*", "*trafficjunky*", "*popads*",
            ])
        except Exception:
            pass

    def stop(self):
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        self.ws = None
        if self.proc:
            try:
                subprocess.run(["taskkill", "/PID", str(self.proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            self.proc = None

    def eval_json(self, js, timeout_s=60):
        """在页面里跑一段 async JS，返回它 JSON.stringify 出来的对象。"""
        res = self._call("Runtime.evaluate", expression=js,
                         returnByValue=True, awaitPromise=True)
        val = (res.get("result") or {}).get("value")
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None

    def list_rows(self, path):
        """直接在页面里解析列表，只把几十行 JSON 传回来（不用搬 200KB HTML）。

        失败时退回上一次成功的结果（last_good），避免电视端看到整页空白。
        """
        try:
            self.ensure()
            if not self._ensure_ready():
                log("[list] 页面没就绪", path)
            url = SITE + path
            js = r"""(async () => {
  try {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 45000);
    const r = await fetch(%s, {credentials:'include', cache:'no-store', signal: ctl.signal});
    clearTimeout(to);
    const t = await r.text();
    const d = new DOMParser().parseFromString(t, 'text/html');
    const num = (el) => { if (!el) return 0; const m = (el.textContent||'').match(/(\d+)/); return m ? parseInt(m[1], 10) : 0; };
    const out = []; const seen = new Set();
    d.querySelectorAll('a.album-link').forEach(a => {
      const href = a.getAttribute('href') || '';
      const m = href.match(/\/a\/([A-Za-z0-9]+)/);
      if (!m) return;
      const id = m[1];
      if (seen.has(id)) return;
      seen.add(id);
      let card = a;
      while (card && !(card.id || '').startsWith('album-')) card = card.parentElement;
      const pic = (card && card.querySelector('img.album-thumbnail')) || null;
      const usr = card && (card.querySelector('.album-user') || card.querySelector('img.avatar'));
      let uname = usr ? (usr.getAttribute('alt') || usr.textContent || '').trim() : '';
      uname = uname.replace(/'s avatar$/i, '');
      const tEl = card && card.querySelector('a.album-title, .album-title');
      const title = (tEl && (tEl.textContent || '').trim()) || (pic && (pic.getAttribute('alt') || '').trim()) || id;
      out.push({
        id: id,
        name: title,
        pic: pic ? (pic.getAttribute('src') || '') : '',
        nv: num(card && card.querySelector('.album-videos')),
        np: num(card && card.querySelector('.album-images')),
        user: uname
      });
    });
    return JSON.stringify({status: r.status, len: t.length, rows: out});
  } catch (e) { return JSON.stringify({error: String(e)}); }
})()""" % json.dumps(url)
            data = None
            for attempt in range(2):
                data = self.eval_json(js)
                if data and data.get("rows"):
                    break
                log("[list] %s 第 %d 次失败: %s" % (path, attempt + 1, (data or {}).get("error")))
                time.sleep(0.4)
                self.ensure()
            if data and data.get("rows"):
                self.last_good[path] = data["rows"]
                return data["rows"]
            stale = self.last_good.get(path)
            if stale:
                log("[list] %s 用上次缓存顶替（%d 条）" % (path, len(stale)))
                return stale
            return []
        except Exception as e:
            log("[list] %s 异常: %s" % (path, e))
            return self.last_good.get(path, [])

    def detail_rows(self, aid):
        with self.detail_lock:
            hit = self.detail_cache.get(aid)
            if hit and time.time() - hit[0] < self.detail_ttl:
                return hit[1]
        js = r"""(async () => {
  try {
    const ctl = new AbortController();
    const to = setTimeout(() => ctl.abort(), 45000);
    const r = await fetch('/a/%s', {credentials:'include', cache:'no-store', signal: ctl.signal});
    clearTimeout(to);
    const t = await r.text();
    const d = new DOMParser().parseFromString(t, 'text/html');
    const h1 = d.querySelector('h1');
    const og = d.querySelector('meta[property="og:image"]');
    const imgs = [...d.querySelectorAll('img')].map(i => i.getAttribute('src'))
      .filter(u => u && /s\d+\.erome\.com/.test(u) && !/thumbs/.test(u));
    // 一个专辑里可能有很多个视频：按 div.video 逐个取（不再只留 4 个）
    const vids = [];
    d.querySelectorAll('div.video').forEach(div => {
      const v = div.querySelector('video');
      if (!v) return;
      const cand = [...v.querySelectorAll('source')].map(s => ({
        src: s.getAttribute('src') || '',
        type: (s.getAttribute('type') || '').toLowerCase(),
        res: parseInt(s.getAttribute('res') || '0', 10) || 0
      })).filter(o => o.src && !/_audio/i.test(o.src) && !o.type.includes('audio'));
      if (!cand.length) return;
      cand.sort((a, b) => b.res - a.res);
      const span = div.querySelector('.duration');
      vids.push({src: cand[0].src, res: cand[0].res, dur: span ? (span.textContent || '').trim() : ''});
    });
    if (!vids.length) {
      // 兜底：老结构 / 弹层里才有 source 的情况
      const seen = new Set();
      [...d.querySelectorAll('source')].forEach(s => {
        const u = s.getAttribute('src') || '';
        if (!u || seen.has(u) || /_audio/i.test(u)) return;
        seen.add(u);
        vids.push({src: u, res: parseInt(s.getAttribute('res') || '0', 10) || 0, dur: ''});
      });
    }
    const name = h1 ? (h1.textContent || '').trim() : (d.title || '').split(' - ')[0];
    return JSON.stringify({status: r.status, name: name,
      poster: og ? og.getAttribute('content') : (imgs[0] || ''),
      videos: vids, srcs: vids.map(v => v.src), pics: imgs.length});
  } catch (e) { return JSON.stringify({error: String(e)}); }
})()""" % aid
        data = None
        for attempt in range(2):
            try:
                self.ensure()
                data = self.eval_json(js)
            except Exception as e:
                log("[detail] %s 第 %d 次异常: %s" % (aid, attempt + 1, e))
                data = None
            if data and not data.get("error") and data.get("srcs"):
                break
            time.sleep(0.5)
        if data and not data.get("error"):
            with self.detail_lock:
                self.detail_cache[aid] = (time.time(), data)
            return data
        with self.detail_lock:
            hit = self.detail_cache.get(aid)
        if hit:
            log("[detail] %s 用缓存顶替" % aid)
            return hit[1]
        return data

    def _ensure_ready(self, timeout_s=25):
        """确保当前标签页停在 erome 且已加载完，否则页面内 fetch 会报 Failed to fetch。"""
        end = time.time() + timeout_s
        while time.time() < end:
            try:
                r = self._call("Runtime.evaluate", expression=(
                    "JSON.stringify({href:location.href,ready:document.readyState})"),
                    returnByValue=True)
                info = json.loads((r.get("result") or {}).get("value") or "{}")
            except Exception:
                info = {}
            href = info.get("href") or ""
            if "erome.com" in href and info.get("ready") == "complete":
                return True
            if "erome.com" not in href:
                try:
                    self._call("Page.navigate", url=SITE)
                except Exception:
                    pass
            time.sleep(1.0)
        return False

    def fetch(self, path, timeout_s=30):
        self.ensure()
        key = path
        hit = self.cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        if not self._ensure_ready():
            log("[fetch] 页面没就绪，仍尝试请求", path)
        url = SITE + path
        js = ("(async () => {"
              "  try {"
              "    const r = await fetch(%s, {credentials:'include', cache:'no-store'});"
              "    const t = await r.text();"
              "    return JSON.stringify({status: r.status, len: t.length, html: t.slice(0, 900000)});"
              "  } catch (e) { return JSON.stringify({error: String(e)}); }"
              "})()" % json.dumps(url))
        data = {}
        for attempt in range(3):
            res = self._call("Runtime.evaluate", expression=js,
                             returnByValue=True, awaitPromise=True)
            val = (res.get("result") or {}).get("value") or "{}"
            data = json.loads(val)
            if not data.get("error"):
                break
            log("[fetch] 第 %d 次失败 %s: %s" % (attempt + 1, path, data["error"]))
            time.sleep(1.5)
            self._ensure_ready()
        if data.get("error"):
            raise RuntimeError(data["error"])
        html = data.get("html") or ""
        self.cache[key] = (time.time(), html)
        return html


BROWSER = Browser()


# ---------- 解析 ----------
def parse_rows(html, video_only=VIDEO_ONLY):
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
        aid = link.rstrip("/").split("/")[-1]
        t = _TITLE_RE.search(b)
        pic = _IMG_RE.search(b)
        user = _USER_RE.search(b)
        marks = []
        if nv:
            marks.append("视频%d" % nv)
        if np_:
            marks.append("图%d" % np_)
        if user:
            marks.append(clean(user.group(1)))
        rows.append({
            "vod_id": aid,
            "vod_name": clean(t.group(1)) if t else aid,
            "vod_pic": pic.group(1) if pic else "",
            "vod_remarks": " · ".join(marks),
        })
    seen, out = set(), []
    for r in rows:
        if r["vod_id"] in seen:
            continue
        seen.add(r["vod_id"])
        out.append(r)
    return out


def resolve_tid(tid):
    """电视端有时发数字分类 id（1 基或 0 基），这里统一映射成 CATS 的 key。"""
    keys = [k for k, _ in CATS]
    tid = (tid or "").strip()
    if tid in keys:
        return tid
    if tid.isdigit():
        i = int(tid)
        if 1 <= i <= len(keys):
            return keys[i - 1]
        if 0 <= i < len(keys):
            return keys[i]
    return keys[0]


def to_row(raw, video_only=VIDEO_ONLY):
    """把页面里解析出来的原始条目转成 CMS 行；纯图集按开关过滤掉。"""
    nv = int(raw.get("nv") or 0)
    np_ = int(raw.get("np") or 0)
    if video_only and nv <= 0:
        return None
    marks = []
    if nv:
        marks.append("视频%d" % nv)
    if np_:
        marks.append("图%d" % np_)
    if raw.get("user"):
        marks.append(clean(raw["user"]))
    aid = raw.get("id") or ""
    if not aid:
        return None
    info = dur_info(aid)
    if info and info.get("max"):
        # 海报上直接看得到「最长 02:31」，避免点进很短的视频
        marks.insert(1 if nv else 0, "最长 " + fmt_dur(info["max"]))
    return {
        "vod_id": aid,
        "vod_name": clean(raw.get("name") or aid) or aid,
        "vod_pic": raw.get("pic") or "",
        "vod_remarks": " · ".join(marks),
    }


def prefetch_durations(aids, limit=24):
    """后台补齐时长（第一次没有缓存时，海报上先只显示视频数）。"""
    todo = [a for a in aids if a and not dur_info(a)][:limit]
    if not todo:
        return
    with _prefetch_lock:
        if _prefetch_running[0]:
            return
        _prefetch_running[0] = True

    def worker():
        try:
            done = 0
            for aid in todo:
                try:
                    d = BROWSER.detail_rows(aid) or {}
                    note_dur(aid, d.get("videos") or [])
                    done += 1
                except Exception as e:
                    log("[dur] %s 取时长失败: %s" % (aid, e))
                time.sleep(0.2)
            save_dur()
            log("[dur] 补齐 %d 个专辑的时长" % done)
        finally:
            _prefetch_running[0] = False

    threading.Thread(target=worker, daemon=True).start()


def gather(path_fmt, pg, want=24):
    rows, seen = [], set()
    p = pg
    for _ in range(MAX_PAGES):
        try:
            raw = BROWSER.list_rows(path_fmt % p)
        except Exception as e:
            log("[list] %s 失败: %s" % (path_fmt % p, e))
            break
        if not raw:
            break
        for item in raw:
            r = to_row(item)
            if not r or r["vod_id"] in seen:
                continue
            seen.add(r["vod_id"])
            rows.append(r)
        if len(rows) >= want:
            break
        p += 1
    # 海报上的「最长 mm:ss」来自缓存；没缓存就在后台慢慢补，下次进分类就能看到
    try:
        prefetch_durations([r["vod_id"] for r in rows])
    except Exception:
        pass
    return rows


def parse_detail(aid):
    d = BROWSER.detail_rows(aid)
    if not d or d.get("error"):
        log("[detail] %s 失败: %s" % (aid, (d or {}).get("error")))
        return None
    vids = d.get("videos") or []
    if not vids:
        vids = [{"src": s, "dur": ""} for s in (d.get("srcs") or [])]
    note_dur(aid, vids)
    ds = [secs(v.get("dur") or "") for v in vids]
    ds = [x for x in ds if x > 0]
    return {"aid": aid, "name": d.get("name") or aid, "videos": vids,
            "nv": len(vids), "max_dur": max(ds) if ds else 0,
            "sum_dur": sum(ds),
            "poster": d.get("poster") or "", "pics": d.get("pics") or 0,
            "page": SITE + "/a/" + aid}


def _unused_parse_detail_html(aid):
    html = BROWSER.fetch("/a/%s" % aid)
    if not html:
        return None
    h1 = _H1_RE.search(html)
    name = clean(h1.group(1)) if h1 else aid
    if not h1:
        t = re.search(r"<title>(.*?)</title>", html, re.S)
        if t:
            name = clean(t.group(1)).split(" - ")[0]
    srcs = []
    for s in _SOURCE_RE.findall(html):
        if s not in srcs:
            srcs.append(s)
    pics = [u for u in re.findall(r'https?://s\d+\.erome\.com/[^"\'\s]+\.(?:jpg|jpeg|png)', html)
            if "/thumbs/" not in u]
    return {"aid": aid, "name": name, "srcs": srcs[:4], "poster": pics[0] if pics else "",
            "pics": len(pics), "page": SITE + "/a/" + aid}


def class_items():
    return [{"type_id": k, "type_name": n} for k, n in CATS]


def pack(items, page=1, pagecount=999, total=9999, msg="ok", with_class=False):
    body = {"code": 1, "msg": msg, "page": page, "pagecount": pagecount,
            "limit": len(items) or 20, "total": total, "list": items}
    if with_class:
        body["class"] = class_items()
        body["filters"] = {}
    return body


# ---------- 播放代理 ----------
CHUNK_MAX = 1536 * 1024   # 单片 1.5MB：erome CDN 单连接约 0.6MB/s，一片约 2.5 秒；盒子播放器单请求超时更短，片不能大


def _parse_range(h):
    """'bytes=123-' / 'bytes=123-456' -> (123, 456|None)"""
    if not h:
        return None
    m = re.match(r"\s*bytes\s*=\s*(\d+)\s*-\s*(\d*)\s*$", h)
    if not m:
        return None
    return int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def proxy_play(handler, url):
    """转发 CDN 视频，补 Referer（裸请求 403）。

    erome 的 CDN 单连接只有 ~0.6 MB/s。盒子播放器读完一段就关连接（日志里全是 10053），
    所以长视频不能一次给完：按 3MB 切片，每片几秒就传完，播放器会自己接着要下一片。
    """
    m = re.search(r"/a/([A-Za-z0-9]+)", url)
    ref = ("%s/a/%s" % (SITE, m.group(1))) if m else (SITE + "/")
    req_rng = _parse_range(handler.headers.get("Range"))
    start = 0
    end = None
    if req_rng:
        start, end = req_rng
        if end is None or end - start + 1 > CHUNK_MAX:
            end = start + CHUNK_MAX - 1
    headers = {"User-Agent": UA, "Referer": ref, "Accept": "*/*"}
    if req_rng:
        headers["Range"] = "bytes=%d-%d" % (start, end)
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=120, context=_CTX)
    except Exception as e:
        log("[play] open failed: %s (%s)" % (e, url.split("?")[0][-40:]))
        try:
            handler.send_error(502, "bad gateway")
        except Exception:
            pass
        return
    total = None
    cr = resp.headers.get("Content-Range") or ""
    mm = re.search(r"/(\d+)\s*$", cr)
    if mm:
        total = int(mm.group(1))
    elif resp.headers.get("Content-Length"):
        total = int(resp.headers["Content-Length"])
    try:
        if req_rng and total:
            # 明确回 206 + 精确区间，播放器才知道「还能往后要」
            last = min(end, total - 1)
            body_len = last - start + 1
            handler.send_response(206)
            handler.send_header("Content-Range", "bytes %d-%d/%d" % (start, last, total))
            handler.send_header("Content-Length", str(body_len))
        else:
            handler.send_response(resp.status)
            v = resp.headers.get("Content-Length")
            if v:
                handler.send_header("Content-Length", v)
        handler.send_header("Content-Type", resp.headers.get("Content-Type") or "video/mp4")
        handler.send_header("Accept-Ranges", "bytes")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.send_header("Content-Disposition", 'inline; filename="video.mp4"')
        handler.send_header("Connection", "close")
        handler.end_headers()
        if handler.command == "HEAD":
            log("[play] HEAD %s -> %s" % (url.split("?")[0][-40:], resp.status))
            return
        sent = 0
        while True:
            chunk = resp.read(262144)
            if not chunk:
                break
            handler.wfile.write(chunk)
            sent += len(chunk)
            try:
                handler.wfile.flush()
            except Exception:
                break
    except Exception as e:
        log("[play] stopped after %d bytes: %s" % (sent, e))
    finally:
        try:
            handler.wfile.flush()
        except Exception:
            pass
    log("[play] %s range=%s -> %s, %d bytes" % (
        url.split("?")[0][-40:], handler.headers.get("Range") or "-", resp.status, sent))


def proxy_url(host, src):
    """播放地址必须带 .mp4 后缀：不少盒子的播放器靠扩展名挑解码器，没后缀会走崩溃分支。"""
    tail = src.split("?")[0].rstrip("/").split("/")[-1] or "video"
    if not tail.lower().endswith((".mp4", ".m4v")):
        tail = "video.mp4"
    return "http://%s/play/%s?u=%s" % (host, urllib.parse.quote(tail, safe=""),
                                       urllib.parse.quote(src, safe=""))


# ---------- HTTP ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "erome-gateway/" + VER
    protocol_version = "HTTP/1.0"

    def log_message(self, fmt, *args):
        return

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            pass

    def _host(self):
        return self.headers.get("Host") or ("%s:%d" % self.server.server_address)

    def do_HEAD(self):
        u = urllib.parse.urlsplit(self.path)
        if u.path == "/play" or u.path.startswith("/play/"):
            q = urllib.parse.parse_qs(u.query)
            src = (q.get("u") or [""])[0]
            if not src:
                self.send_error(400, "missing u")
                return
            m = re.search(r"/a/([A-Za-z0-9]+)", src)
            ref = ("%s/a/%s" % (SITE, m.group(1))) if m else (SITE + "/")
            req = urllib.request.Request(src, headers={"User-Agent": UA, "Referer": ref},
                                         method="HEAD")
            try:
                resp = urllib.request.urlopen(req, timeout=30, context=_CTX)
            except Exception as e:
                log("[play-head] failed:", e)
                self.send_error(502, "bad gateway")
                return
            self.send_response(resp.status)
            for k in ("Content-Type", "Content-Length", "Accept-Ranges"):
                v = resp.headers.get(k)
                if v:
                    self.send_header(k, v)
            self.send_header("Connection", "close")
            self.end_headers()
            return
        self.send_error(404, "not found")

    def do_GET(self):
        u = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path

        if path == "/":
            self._json({"ok": True, "site": "erome-gateway", "ver": VER,
                        "cats": [{"type_id": k, "type_name": n} for k, n in CATS],
                        "api": "/api.php/provide/vod/"})
            return

        if path == "/play" or path.startswith("/play/"):
            src = (q.get("u") or [""])[0]
            if not src:
                self.send_error(400, "missing u")
                return
            proxy_play(self, src)
            return

        if path.rstrip("/") in ("/api.php/provide/vod", "/api.php/provide/vod/index.php"):
            self.api(q)
            return

        self.send_error(404, "not found")

    def api(self, q):
        ac = (q.get("ac") or [""])[0]
        ids = (q.get("ids") or [""])[0]
        wd = (q.get("wd") or [""])[0]
        tid = (q.get("t") or [""])[0]
        pg = (q.get("pg") or ["1"])[0]
        try:
            pg = max(1, int(pg))
        except Exception:
            pg = 1

        if ids:
            aid = ids.split(",")[0].strip()
            if aid.startswith("http"):
                aid = aid.rstrip("/").split("/")[-1]
            try:
                d = parse_detail(aid)
                save_dur()
            except Exception as e:
                log("[detail] %s 失败: %s" % (aid, e))
                d = None
            if not d:
                self._json(pack([{"vod_id": aid, "vod_name": "EroMe " + aid,
                                  "vod_content": "详情页拉取失败"}]))
                return
            host = self._host()
            vids = d["videos"]
            # 一个合集里的多个视频 = 多集（不是多线路）；按时长从长到短排，最长的先播
            ordered = sorted(vids, key=lambda v: secs(v.get("dur") or ""), reverse=True)
            eps = []
            for i, v in enumerate(ordered, 1):
                label = "第%02d集" % i
                dd = fmt_dur(secs(v.get("dur") or ""))
                if dd:
                    label += " " + dd
                eps.append("%s$%s" % (label, proxy_url(host, v["src"])))
            marks = ["视频%d" % d["nv"]]
            if d["max_dur"]:
                marks.append("最长 " + fmt_dur(d["max_dur"]))
            if d["pics"]:
                marks.append("图%d" % d["pics"])
            item = {
                "vod_id": d["aid"],
                "vod_name": d["name"],
                "vod_pic": d["poster"],
                "vod_remarks": " · ".join(marks),
                "vod_content": "[网关 %s] %s%s" % (
                    VER, " · ".join(marks),
                    "" if eps else "；该专辑没有视频（纯图集）"),
                "vod_play_from": "EroMe" if eps else "",
                "vod_play_url": "#".join(eps),
            }
            self._json(pack([item], 1, 1, 1))
            return

        if wd:
            rows = gather("/search?q=%s&page=%%d" % urllib.parse.quote(wd), pg)
            self._json(pack(rows, pg, 999, 9999, with_class=True))
            return

        if not tid:
            rows = gather(LIST_PATH["latest"], pg)
            self._json(pack(rows, pg, 999, 9999, with_class=True))
            return

        tid = resolve_tid(tid)
        rows = gather(LIST_PATH[tid], pg)
        self._json(pack(rows, pg, 999, 9999, with_class=True))


class Tee(object):
    def __init__(self, fh):
        self.fh = fh

    def write(self, s):
        try:
            self.fh.write(s)
            self.fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            self.fh.flush()
        except Exception:
            pass


def watchdog(stop_evt, interval=60):
    """每 60 秒看一眼：浏览器死了就重连/重启，避免「有时可以有时不行」。"""
    while not stop_evt.wait(interval):
        try:
            if not BROWSER.alive():
                log("[watch] chrome down, restarting")
                BROWSER.ws = None
                BROWSER.start()
            elif BROWSER.ws is None:
                log("[watch] ws missing, reconnecting")
                BROWSER._connect()
        except Exception as e:
            log("[watch] failed:", e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8082)
    ap.add_argument("--log", default="")
    args = ap.parse_args()

    if args.log:
        fh = open(args.log, "a", encoding="utf-8")
        sys.stdout = Tee(fh)
        sys.stderr = Tee(fh)

    # 单实例
    s = socket.socket()
    try:
        if s.connect_ex(("127.0.0.1", args.port)) == 0:
            log("[http] port %d already in use, another gateway is running" % args.port)
            return 100
    finally:
        s.close()

    log("erome-gateway %s starting on 0.0.0.0:%d" % (VER, args.port))
    load_dur()
    BROWSER.start()
    try:
        raw = BROWSER.list_rows(LIST_PATH["feed"] % 1)
        rows = [r for r in (to_row(x) for x in raw) if r]
        log("[warm] feed %d items（原始 %d 条）" % (len(rows), len(raw)))
        if not rows:
            log("[warm] feed 为空：可能是 cookie 失效（重跑 erome_login.py --grab）")
        else:
            prefetch_durations([r["vod_id"] for r in rows], limit=12)
    except Exception as e:
        log("[warm] failed:", e)

    stop_evt = threading.Event()
    threading.Thread(target=watchdog, args=(stop_evt,), daemon=True).start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    srv.daemon_threads = True
    log("[http] listening")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop_evt.set()
        save_dur()
        BROWSER.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
