# SpankBang → TVBox 网关（本机版）

把 spankbang.com 变成 TVBox / CatVod / 影视仓能用的 `type=1` 源。

## 先看：不用网关的两条路，都试过了

| 办法 | 结果 |
|---|---|
| 换镜像域名 | `mirror_hunt.py` 扫了 195 个候选，**命中 0**（详见文末「镜像猎手」） |
| 借别人的过盾网关 | `py.fzcrym.link:1314`（supjav 用的那个）从本机超时，不可靠 |

所以这个网关才存在。

## 为什么需要它

spankbang.com 前面挂着 Cloudflare **托管质询**（响应头 `Cf-Mitigated: challenge`）：

```
HTTP/1.1 403 Forbidden
Cf-Mitigated: challenge
Server: cloudflare
CF-RAY: a5e898dabcce8bc6-SIN
```

- 换 UA、换 TLS 指纹（curl_cffi 的 chrome131 / chrome124 / chrome120 / safari17_0）全部超时或 403
- 无头 Chrome（`--headless=new`）同样只拿到 `Just a moment...`
- 所有镜像域名（spankbang.party / .top / .club / .porn …）扫了一遍，要么同样吃质询，要么是停放页

TVBox 的 spider 跑在 OkHttp / drpy 里，没有浏览器环境，永远过不了这一层 —— 所以官方配置里那条 `🔞[待修复]spankbang[XYQHiker]` 才一直修不好。

**本网关的做法**：起一个有头 Chrome（窗口挪到屏幕外），用 CDP 驱动它 —— 真浏览器能自动过质询 —— 再把页面解析成 MacCMS JSON 吐给 TVBox。

取数据这一层后来改成了**页面内 `fetch()`**（在 Chrome 的页面上下文里发请求，复用它的 TLS 指纹与 cookie），比整页渲染快一个数量级，细节见下面的「为什么这么快/为什么这么慢」。

## 启动

双击 `start.cmd`（或 `python sbgateway.py --port 8080`）。

启动后会看到：

```
[dns] spankbang.com -> ['104.19.239.156', '104.18.96.242']
[chrome] ready on port 9335
[http] http://0.0.0.0:8080/api.php/provide/vod/
```

> 本机 DNS 把 spankbang.com 解析到 `175.139.142.25`（黑洞），网关启动时会走 Cloudflare DoH 拿真实边缘 IP，再用 `--host-resolver-rules` 灌给 Chrome，所以不用改 hosts。

## TVBox 配置条目

把下面这条加进你的 `tv18.json` 的 `sites` 数组（IP 换成运行网关那台 PC 的局域网地址）：

```json
{
  "key": "spankbang-lan",
  "name": "SpankBang[网关]",
  "type": 1,
  "api": "http://10.126.39.223:8080/api.php/provide/vod/",
  "searchable": 1,
  "quickSearch": 1
}
```

本机当前的局域网地址：

| 接口 | IPv4 | 状态 |
|---|---|---|
| Wi-Fi 2（Wifi6 USB） | `10.126.39.223` | 在用，默认路由 |
| Ethernet | `192.168.1.101` | 未连接 |

## 防火墙（重要）

当前网络位置是 **公用（Public）**，Windows 会拦掉 8080 的入站连接。以下命令需要**管理员**权限执行一次：

```cmd
netsh advfirewall firewall add rule name="SpankBang TVBox Gateway 8080" dir=in action=allow protocol=TCP localport=8080
```

或者把网络改成专用（同样是管理员）：

```powershell
Set-NetConnectionProfile -InterfaceAlias "Wi-Fi 2" -NetworkCategory Private
```

验证：在手机/电视浏览器打开 `http://10.126.39.223:8080/`，应返回

```json
{"ok": true, "site": "spankbang-gateway", "via": "headful chrome cdp", ...}
```

## 接口

| 请求 | 说明 |
|---|---|
| `?ac=list&t=new&pg=1` | 最新（12–20s，之后 5 分钟走缓存） |
| `?ac=list&t=trending&pg=2` | 热门，支持翻页 |
| `?ac=list&t=popular` / `t=upcoming` | 最多播放 / 即将推出 |
| `?ac=list&wd=日本` | 搜索 |
| `?ac=detail&ids=/xxxx/video/yyyy` | 详情 + 播放地址 |

播放地址给出 5 个线路：`1080p / 720p / 480p / 240p`（直连 mp4，ExoPlayer 最稳）+ `HLS`（master.m3u8）。

## 已知限制

1. **PC 必须开着**，网关一关 TVBox 就没源。可以把 `start.cmd` 丢进 `shell:startup` 自启。
2. **列表 8–20 秒**，详情 10–20 秒 —— 每页都要真浏览器渲染一次。同一 URL 缓存 5 分钟。
3. **直链带 token**（`?secure=...&_tid=...`），有效期约 2 小时。过期的重新进详情页刷新即可。注意 token 必须**完整**保留，少一个 `&m=47&d=1&_tid=` 参数就会变成 `502 error code`。
4. 只处理 spankbang。**erome 不适用**：它是图片相册站 + 登录墙，不是视频站。
5. 首屏那张卡片是站点置顶推荐，各分类第一张可能相同，不是 bug。

## 闲置自动关 Chrome（省内存）

网关平时只在你点开的时候才需要一个真 Chrome（Cloudflare 只放行有头浏览器）。
所以它现在是**按需存活**的：

- 启动后 Chrome 只活到「预热四个分类」结束；
- 之后 **10 分钟没有请求**，`[idle]` 线程会把 Chrome 关掉（日志：`[idle] 600 秒没有请求，关掉 Chrome 释放内存`），任务管理器里那个带 `--remote-debugging-port=9335` 的 chrome.exe 会消失；
- 下一个请求进来时，先回**磁盘快照**（`list_snapshot.json`，首屏 4 个分类的最后一版，0.2 秒内返回），同时在后台把 Chrome 重新拉起来重新渲染，所以你不用等冷启动；
- 渲染过程中绝不会被关（`busy` 计数保护），预热没跑完也不会被关。

调时间：

```
python sbgateway.py --port 8080 --idle-minutes 30     # 30 分钟
python sbgateway.py --port 8080 --idle-minutes 0      # 一直开着，永不关
```

`start.cmd` 里已经写成 10 分钟。

## 任务栏里那个多出来的 Chrome 是什么？（点它没反应是正常的）

它就是这个网关的浏览器：`chrome.exe --remote-debugging-port=9335 --user-data-dir=%TEMP%\sb-gateway-profile`。
必须**有头**（Cloudflare 只放行真浏览器），所以会有一个进程。

以前的处理是把窗口 `ShowWindow(SW_HIDE)`，但窗口被移到 `-2400,-2400` 时 Windows 仍算它「可见」，
于是任务栏会留下一个 Chrome 图标——点它什么也不会发生（窗口在屏幕外）。
现在启动时会额外做两件事：

1. 加 `WS_EX_TOOLWINDOW` 去掉任务栏/Alt+Tab 条目；
2. 移到屏幕外再 `SW_HIDE`。

想亲眼看它在干什么（比如要手动点一下 Cloudflare 验证）：

```
cd C:\Users\plsharevme\tvbox-gateway
python chrome_window.py show     # 搬到屏幕中间
python chrome_window.py hide     # 再藏回去
python chrome_window.py status   # 看窗口状态
```

也可以直接双击 `chrome-window.cmd show` / `chrome-window.cmd hide`。
另外 Chrome 参数里加了 `--disable-session-crashed-bubble --hide-crash-restore-bubble`，
不会再弹「Restore pages?」。

## 故障排查

| 现象 | 处理 |
|---|---|
| TVBox 里列表空 | 先在手机浏览器打开 `http://10.126.39.223:8080/`，不通就是防火墙 |
| 一直转圈 | 看网关窗口有没有 `[chrome] ready`；Chrome 崩了会自动重启（start.cmd 里 5s 重试） |
| 能出列表、播放失败 | 直链 token 过期，退出详情页重新进 |
| 页面变成 `Just a moment...` | 质询没过，关掉网关窗口重开（Chrome 会换新会话） |

## 文件

```
sbgateway.py   网关主程序（HTTP 服务 + CDP 驱动 + 解析）
start.cmd      启动脚本（自动重启）
README.md      本文件
```

## 播放代理（/play?u=）

详情接口返回的 `vod_play_url` 不是 CDN 直链，而是：

    http://<网关IP>:8080/play?u=<URL 编码后的原始 mp4 / m3u8>

原因：盒子直连 `vdownload-*.sb-cd.com` 时常失败（DNS、TLS、CDN 校验都可能挡）。
改由网关代取，盒子只需要能连本机 8080。

- 支持 `Range`（拖进度条 → 206 Partial Content）
- 支持 `HEAD`（播放器取文件长度）
- 日志里能看到每条：`[play] <url> -> 206, <bytes>`

## 已知耗时

- 列表页：命中缓存 ~0.05s；冷启动渲染 3-8s（启动时已预热四个分类）
- 详情页：首次 8-15s（真 Chrome 渲染视频页），同一片再看 ~0.01s
- 启动后前 20 秒内 Chrome 正在预热，此时点视频会排队，属正常

## 播放时 TVBox 直接崩掉怎么办

播放响应做了三处保守化处理：

1. 播放地址带 `.mp4` / `.m3u8` 后缀（`/play/1080p.mp4?u=...`）。不少内核靠扩展名挑解码器，无后缀会走到 native 崩溃分支。
2. 播放响应按 **HTTP/1.0** + `Connection: close` 发。HTTP/1.1 keep-alive 语义在自带 OkHttp 的处理链里容易踩异常。
3. 不再给出 HLS(m3u8) 线路。m3u8 里的切片地址还在 CDN 域名上，盒子自己取不到，播放器一旦选到就崩。

### 低码率入口（老盒子/硬解弱）

    http://<本机IP>:8080/api.php/provide/vod/q480/

只回 480p / 240p 两条线。同理 `q720/`、`q240/`。

### 单实例

端口已被占用时新进程直接退出（返回码 100），`start.cmd` 会关掉这个窗口。
两个实例同时跑会抢同一个 Chrome 调试端口，可能吐出半截流——那也是播放器崩溃的常见诱因。

## 筛选（TVBox 的「筛选」条）

`ac=list` / `ac=detail&t=` 的响应里带 `filters`，四个分类都有三组：

| 键 | 名称 | 取值 | 怎么落到站内 |
|---|---|---|---|
| `tag` | 标签 | **137 个**，分五段：中文/日文站内 23 → 日本/JAV 18 → 东南亚 8 → 孕产 15 → Camgirl 14 → 通用 58 | 走 `/s/<tag>/` 标签页 |
| `sort` | 排序 | 默认 / 最新发布 / 最热 | `?o=new` / `?o=top` |
| `date` | 时间 | 全部 / 最近约 1 天 / 2 天 / 3 天 | 合并前 2/3/4 页（每页 72 条），`pagecount` 置 1 |

说明：站点本身没有「日期区间」参数，`/new_videos/` 是倒序的，所以「最近 N 天」= 取前 N 页。
合并过的结果只返回一页，翻页按钮会消失，这是刻意的——不然会一直翻到重复内容。

### 东南亚 / 孕产两组（逐条验过的条数）

站点上这两类都有片，`f={"tag":"..."}` 实测（每页上限 64）：

| 中文名 | slug | 条数 | | 中文名 | slug | 条数 |
|---|---|---|---|---|---|---|
| 印尼 | `indonesian` | 64 | | 怀孕 | `pregnant` | 64 |
| 印尼业余 | `indonesian+amateur` | 64 | | 孕妇性爱 | `pregnant+sex` | 64 |
| 印尼熟女 | `indonesian+milf` | 61 | | 孕妇内射 | `pregnant+creampie` | 64 |
| 印尼内射 | `indonesian+creampie` | 29 | | 孕妇大肚 | `pregnant+belly` | 64 |
| 马来西亚 | `malaysian` | 64 | | 孕晚期 | `9+months+pregnant` | 58 |
| 马来 | `malay` | 64 | | 妊娠 | `pregnancy` | 64 |
| 马来业余 | `malaysian+amateur` | 44 | | 播种 | `impregnation` | 64 |
| 马来少女 | `malay+teen` | 43 | | 哺乳 / 泌乳 | `lactation` / `milking` | 64 / 64 |

没放进来的两个：`malaysian+teen`（14 条，首条是站内推广，实际内容稀薄）、`malaysian+milf`（8 条，同样掺推广）。
「受孕」在中文段已有 `孕ませ`（日文站内词），孕产段里另设 `播种` 对应英文 `impregnation`，两者结果不同。

### TVBox 实际怎么传参（很重要）

它**不是**按 `tag=japanese&sort=new` 这样传的，而是把整组选择打包成**一个 URL 编码的 JSON**：

    /api.php/provide/vod/?f=%7B%22tag%22%3A%22blowjob%22%2C%22sort%22%3A%22top%22%7D&t=new&ac=detail&pg=1

也就是 `f={"tag":"blowjob","sort":"top"}`。网关会优先解析 `f`，同时也兼容独立的 `tag=` / `sort=` / `date=`。
早期版本只读独立参数，所以「选了筛选、海报不动」——现在已经修好了。

### 标签页的两个网格（另一个坑）

`/s/<tag>/` 页面里有 **两个** `x-data="videoList"` 网格：第一个是站内推广轮播（8 条，所有标签页完全一样），
第二个才是这个标签的真实结果。网关现在按条目数挑最大的那个网格，所以换标签内容一定跟着变。
（分类页同理，因此每页从 72 条变成 64 条——那 8 条推广不再混进来。）

## 为什么这么快 / 为什么这么慢（三个实测教训）

这一层层挖下来，性能问题几乎全不在「抓页面」本身，而在传输和调度：

### 1. 整页渲染 20–30 秒 → 页面内 fetch 0.5–2 秒

整页导航要等 HTML、脚本、XHR、懒加载都跑完，一次 20–30 秒；TVBox 的详情超时只有十秒上下，
于是「点进去一直转圈」——日志里连一条 `/play` 请求都没有，因为播放器根本没拿到播放地址。

改成在页面上下文里 `fetch(url, {credentials:'include'})`，复用 Chrome 自己的指纹和 cookie，
**4 秒 → 0.5–2 秒**。注意裸 urllib 不行：`cf_clearance` 绑 TLS 指纹，换个客户端就 403。

### 2. 标签页要停在一个「同源、没有 JS」的文档上

停在首页（37 个脚本）时，页面事件循环会把 `fetch` 的 Promise 兑现时间拖后两秒多：
页面内 `performance.now()` 只报 0.6 秒，CDP 却 3 秒后才回。改成先导航到
`https://spankbang.com/robots.txt`（Chrome 把它当纯文本渲染，`document.scripts.length === 0`），
延迟立刻消失。

### 3. CDP 回传体积就是延迟：618 KB ≈ 3.4 秒

| 回传体积 | evaluate 往返 |
|---|---|
| 50 KB | 0.55s |
| 200 KB | 1.48s |
| 618 KB（整页） | 3.41s |

所以现在在**页面里先把无关部分剪掉**再回传（`Browser.fetch_slim`）：

- 列表页：只留最大的结果网格，去掉 `<script>` / `<style>` / `class` / `style` / `srcset`，
  618 KB → **282 KB**
- 详情页：只留 `<h1>`、几个 `meta`、以及 `vdownload-*` / `hls-*` 直链，558 KB → 几 KB

效果：翻页 **1.0–1.2 秒**（原来 2.5–4 秒，更早 13–40 秒），详情**首次 1.1 秒 / 缓存 0.01 秒**。

### 4. 后台预取默认关闭

CDP 的 `evaluate` 是串行的（同一把锁）。开着「列表下发后预取前几条详情」时，翻页请求
会被预取挡在后面，实测把筛选请求拖到 10 秒。详情现在自己就只要 1 秒，所以预取默认 `--prefetch 0`，
想要就自己开。

### 5. 事件帧别解析

`Page` / `Network` / `Runtime` 的**事件**帧不带 `"id"`，一条 evaluate 期间能涌进来几千条。
先做一个 `'"id" in raw'` 的字符串判断再 `json.loads`，省下可观时间。

---

## 镜像猎手 `mirror_hunt.py`

给定一个站点，自动找「同样内容、但没开托管质询」的域名。候选来自四路：

1. **证书透明日志** —— crt.sh（常 502，自动回退 certspotter）
2. **TVBox 规则文件** —— `--from-rule <url>`，把规则作者已经验证过的域名抠出来（最值钱的一路）
3. **跳转链** —— 跟 301/302，并从首页 HTML 里捡同品牌域名
4. **品牌变体** —— 40 个 TLD × 常见前后缀组合

每个候选：DoH 解析真实 IP（绕 ISP 污染，命中黑洞 `175.139.142.25` 直接跳过）→ 带 SNI 直连 →
判 `CF-CHALLENGE` / `PARKED` / `CAM-SQUAT` / `REDIRECT` / `WIN`（全部 DOM 指纹命中）。

```cmd
python mirror_hunt.py spankbang.com --markers 'x-data="videoList",data-testid="video-item",sb-cd.com' --workers 20
python mirror_hunt.py missav.ai --markers missav --from-rule <规则文件URL> --no-variants
```

**正控实测（能命中）**：`missav.ai` + `--from-rule .../tv/py/missav-app.py` →
`missav.app` 677ms、`missav02.xyz` 680ms，两个都 `WIN`（200 且无质询）。

**spankbang 实测（命中 0）**：195 个候选 → `NO-CONNECT 163`、`REDIRECT 12`、
`OK-NOSIG 10`（全是停放页/摄像头站/同名不同站）、`PARKED 1`、`CF-CHALLENGE 1`。
唯一沾边的是子域 `vx.spankbang.com`（Live Cam 分区，不是片库）和 `feedback.spankbang.com`（反馈系统）。
明细在 `_mirror_spankbang2.json`。

结论：**它没有活着的镜像域名**，域名轮换这条路对它是封死的。
