# TVBox 配置项目

一份 TVBox（TV 盒子/电视端播放器）的 18+ 内容订阅配置，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

## 文件

| 文件 | 说明 |
|---|---|
| **`tv18.json`** | 主配置（365 站点）。脚本/jar 从**上游 `tvbw/18-`** 加载 |
| **`tv18-standalone.json`** | **自托管版**。同样的 365 站点，脚本/jar 全部从**本仓库 `resources/`** 加载 |
| `resources/` | 316 个上游文件副本（14.6 MB）：jar、py 脚本、XYQHiker/XBPQ 定义、直播列表 |
| `tools/diag-sites.mjs` | **站点可用性体检**：区分「真死了」和「只是被 ISP 的 DNS 屏蔽」 |
| `tools/build-resources.mjs` | 从上游克隆重建 `resources/` |
| `tools/make-standalone.mjs` | 由 `tv18.json` 重新生成自托管版 |
| `tools/verify-urls.mjs` | 实测配置里每个 URL 能否下载（跟「能不能播」是两件事） |
| `AGENTS.md` | 给 AI 接手看的交接文档 |

**两个配置内容完全相同，唯一区别是脚本从哪里加载。**

## 订阅地址

### 自托管版（推荐 · 不怕上游删库）

```
https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18-standalone.json
```

锁版本、绕 CDN 缓存：

```
https://cdn.jsdelivr.net/gh/ericvlog/tvbox@main/tv18-standalone.json
```

### 上游版（跟着 `tvbw/18-` 更新）

```
https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18.json
```

## 该用哪个

| | 自托管版 | 上游版 |
|---|---|---|
| 上游仓库被删/改名 | ✅ 不受影响 | ❌ 立刻全废 |
| 上游修了脚本 bug | ❌ 你拿不到，要手动同步 | ✅ 自动跟进 |
| 单个站点源站挂了 | ❌ 同样播不了 | ❌ 同样播不了 |

**建议**：用自托管版当主力，上游版留着对比。上游有更新时手动跑一次同步（见 `AGENTS.md`）。

## 自托管版做了什么

把配置里 **316 处**指向 `tvbw/18-` 的引用（3 个 jar + 229 个 py 脚本 + XYQHiker/XBPQ 的
json 定义 + 7.8 MB 直播列表）全部复制到本仓库 `resources/`，并把 URL 改成本仓库路径。
**实测 315 个 URL 全部 200 可达，0 失败。**

## 🔑 在马来西亚：先改 DNS，这一步值 45 个源

**马来西亚 ISP（Time / Unifi / Maxis / Mtel…）按 MCMC 清单做 DNS 污染**：把一大批成人
域名统一解析到**同一个屏蔽 IP**（本机实测：59 个不相关域名全指向 `175.139.142.25`）。
这些站其实活得好好的，**是 ISP 在骗你的设备**。

实测证据：同一时刻、同一条马来西亚网络，把这些域名的 DNS 换成 `1.1.1.1` 后
**12/12 全部 HTTP 200**（chaturbate / xhamster / pornhub / supjav / ggjav / bad.news
/ madou.club / javmenu …）。

**做法（Android TV 盒子）**：设置 → 网络 → **私人DNS（Private DNS）** → 选「主机名」→ 填

```
1dot1dot1.cloudflare-dns.com
```

或在路由器上把 DNS 改成 `1.1.1.1` / `8.8.8.8`（全屋子设备一起生效）。

**收益**：约 **45 个源**立刻可用，从 64% 提到 76%。这比删源、改配置有用得多。
不挂 VPN 也能用——只是 IP 直连，速度快得多。

## 📊 到底多少个能用（实测）

`node tools/diag-sites.mjs` 的结果，测的是站点目标域，不是配置文件：

| 状态 | 数量 |
|---|---|
| 现在就可用 | **233 / 364 = 64%** |
| 改 DNS 后额外救回 | **+45** |
| **改完 DNS 合计可用** | **278 / 364 = 76%** |
| 真死（域名注销，建议删） | 21 |
| 超时但域名正常（多为源站忙/需梯子） | 40 |
| 无固定域名（本地视频、聚合类） | 15 |

**注意 76% 是上限**：这只测到「目标站连得上」。爬虫规则是否还匹配当前网页结构、片子
在不在，测不出来——**爬虫站最常见的死法是网站改版导致脚本失效，域名活着但一搜就报错**。

## ⚠️ 四个必须知道的事

1. **先改 DNS，再谈别的。** 见上面「在马来西亚：先改 DNS」。不改 DNS，45 个源会被误判成死的。
2. **自托管 ≠ 什么都能自己维护。** 你能维护的是「框架侧」——jar、py 脚本、爬虫规则、
   直播列表。配置里 **52 个采集站接口**（`xxzyapi.com` 这类 `api.php` 地址）是
   **第三方站点，不在本仓库里**，它们挂了只能改配置换源，你没法让它们复活。
   另外 **312 个爬虫站**的规则你可以改（就在 `resources/` 里），但它们抓的目标站不归你管。
3. **「配置能加载」≠「每个源都能播放」。** 用 `node tools/diag-sites.mjs` 实测当前是
   64% / 改 DNS 后 76%，且这是上限（原因见上一节）。
4. **App 内必须先删掉旧配置**（不是覆盖）→ **清缓存** → 再粘贴新地址。
   否则 TVBox 会一直用缓存里的旧配置和旧 jar。

## 🖥 第 1 个源 `SpankBang[网关]` 需要本机网关

配置里第一条 `spankbang-lan`（`type: 1`，`api: http://10.126.39.223:8080/api.php/provide/vod/`）
**不是公网采集站**，而是局域网里一台 PC 上跑的本机网关。原因：

spankbang.com 前面挂的是 Cloudflare **托管质询**，换了 UA / TLS 指纹 / 无头浏览器全部被挡：

```
HTTP/1.1 403 Forbidden
Cf-Mitigated: challenge
Server: cloudflare
```

TVBox 的 spider 跑在 OkHttp / drpy 里，没有浏览器环境，过不去 —— 所以配置里原本那条
`🔞[待修复]spankbang[XYQHiker]` 一直修不好。网关的做法是**用有头 Chrome 过质询**，
再把渲染后的页面解析成 MacCMS JSON 吐给 TVBox。

**用法**：

1. 在跑网关的 PC 上双击 `start.cmd`（代码在 PC 的 `C:\Users\plsharevme\tvbox-gateway\`，未入库）
2. TV 盒子与 PC 在**同一局域网**，且 PC 防火墙放行 8080 入站：
   ```cmd
   netsh advfirewall firewall add rule name="SpankBang TVBox Gateway 8080" dir=in action=allow protocol=TCP localport=8080
   ```
3. **PC 关机 / 网关关闭时，这个源就是空的**（其他 364 个源不受影响）

**换机器 / 换网络要改 IP**：`api` 里的 `10.126.39.223` 是写死的内网地址，PC 换了 Wi-Fi
或路由器重新分配 IP 后，把它改成新的内网 IP 即可（`ipconfig` 查）。

抽风的排查顺序：手机浏览器打不开 `http://<IP>:8080/` → 防火墙；打得开但列表转圈 →
网关窗口里的 Chrome 挂了（重开即可）；能出列表但播放失败 → 直链 token 过期（约 2 小时），
重新进详情页。

### 为什么这个网关必须存在（三个墙，别混）

| 墙 | 表现 | 能不能绕 |
|---|---|---|
| 运营商 DNS 污染 | `nslookup` 得到 `175.139.142.25`，连接超时 | 能，DoH / hosts / 网关自己解析 |
| Cloudflare 托管质询 | `403` + `Cf-Mitigated: challenge` + `Just a moment...` | **只能真浏览器**，所以要有头 Chrome |
| 站点登录墙 / CDN 令牌 | 详情里链接 2 小时过期 | 令牌由网关每次现取，过期重进详情 |

注意第一条和第二条**是两回事**：DNS 污染是马来西亚 ISP 干的，跟 Cloudflare 无关；
质询是站点自己开的。很多挂 Cloudflare 的站并不发质询（正常返回 HTML），那种仍然可以
用普通采集接口或 py 爬虫 —— 只有发了质询的站才需要本机网关。

### 速度：慢的地方几乎都不在「抓页面」

网关第一版是整页导航渲染，一次详情 20–30 秒。TVBox 十秒级就超时，日志里连 `/play`
请求都不会出现（表现就是「点进去一直转圈」）。后来改成**页面内 `fetch()`**，
复用 Chrome 的指纹和 cookie，同一份数据 0.5–2 秒。

| 坑 | 现象 | 解法 |
|---|---|---|
| 整页导航 | 详情 20–30 秒，TVBox 超时转圈 | 页面内 `fetch()` + `awaitPromise` |
| 标签页停在首页 | 页面内报 0.6s，CDP 3s 才回 | 先导航到同源无 JS 文档（`/robots.txt`） |
| CDP 回传体积 | 50KB=0.55s / 200KB=1.48s / **618KB=3.41s** | 页面里先剪：列表只留结果网格（618→282KB），详情只留 `h1`+`meta`+直链（558KB→几KB） |
| 事件帧 | 一次 evaluate 涌入几千条事件 | 先判 `'"id"' not in raw` 再解析 |
| 后台预取 | CDP 串行，预取把翻页挡到 10s | 预取默认关（参数 `--prefetch`） |

实测（本机→网关→站点，全链路）：**翻页 1.0–1.2 秒、筛选 0.85–1.43 秒、
详情首次 1.09 秒 / 命中缓存 0.01 秒、播放 `206` 0.8 秒**。

### 播放为什么要走本地反代

详情里的直链是 `https://vdownload-*.sb-cd.com/...mp4?secure=...`，在**盒子侧**未必解析得到
（盒子 DNS、CDN 令牌、TLS 任一环断就黑屏）。所以网关把所有播放地址改写成
`http://<网关IP>:8080/play/720p.mp4?u=<直链>`，由 PC 去拉流再转发，支持 `Range`（`206`）。

两个细节：路径必须带 `.mp4`（不少播放器靠扩展名挑解码器，无后缀会**闪退**）；
m3u8 线路一律不转发（切片还在源站域名上，盒子取不到，播放器选到必崩）。

### 内网 IP 老变怎么办（手机热点上网）

用手机热点，PC 的 IP 每次重连都可能变。三种解法，按「省事程度」排：

**① 自动改配置并推送（已入库，推荐）**

```powershell
node tools\update-gateway-ip.mjs --push
```

脚本会枚举本机网卡 → 逐个探测 `http://<IP>:8080/` 是否返回本网关的签名 →
把两个配置里 `spankbang-lan.api` 改成探测到的那个 IP → commit + push。
`sites` 数组、缩进、无 BOM 全部原样保留（脚本会先校验 `JSON.stringify(...,2)` 能字节级还原，
否则直接拒绝写入）。TVBox 里下拉刷新订阅即可生效。

加 `--set 192.168.43.7` 可跳过探测直接指定；不加 `--push` 就只改本地不发布。

**② Tailscale（一次配置，永久不变）**

PC 和 TV 盒子都装 Tailscale（免费档够用），PC 会拿到固定的 `100.x.y.z`。
把配置里的 `api` 改成 `http://100.x.y.z:8080/api.php/provide/vod/` —— 之后**换任何网络都不用改**，
连 PC 不在同一个 Wi-Fi 也能用。代价是盒子上要装一个 App 并登录。

**③ 固定内网 IP**

路由器（或手机热点）里给这台 PC 做 DHCP 保留地址，或手工设静态 IP。
部分安卓热点的设置里有「已连接设备 → 固定 IP」。改了之后 `api` 就不用再动。

## 历史：原来为什么报 configure 404

原配置 372 处外部引用里 **319 处**指向已消失的仓库 `wanganni/yinshiyuan`
（该仓库、该用户、gitee / gitcode 镜像**全部 404**）。TVBox 加载配置时先下 `spider`
指定的 jar，下不到就报错。修复：325 处重定向到 `tvbw/18-`、`gm.jar`→`GM.jar`
大小写修正、删除上游已彻底缺失脚本的 2 个站点。