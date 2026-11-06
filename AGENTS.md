# AGENTS.md — TVBox 项目

> 给接手的 AI 看。这份文件把「这个项目是什么、坑在哪、怎么验证」讲清楚，
> 让另一个 AI 不用重新踩一遍。

## 项目是什么

一份 **TVBox（电视端播放器）的 18+ 内容订阅配置**，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

- **`tv18.json`** —— 主配置（364 站点，153 KB，合法 JSON，无 BOM）。脚本从**上游 `tvbw/18-`** 加载
- **`tv18-standalone.json`** —— **自托管版**。站点内容完全相同，但 316 处脚本/jar 引用
  改为指向**本仓库 `resources/`**，上游删库也不受影响
- **`resources/`** —— 316 个上游文件副本（14.6 MB）：3 个 jar + 229 个 py 脚本 +
  XYQHiker/XBPQ 的 json 定义 + `tv/做爱大全.txt`（7.8 MB 直播列表）
- **`README.md`** —— 人类可读的说明

## 配置结构（tv18.json 顶层字段）

| 字段 | 内容 |
|---|---|
| `wallpaper` / `spider` / `logo` / `warningText` | 元信息。**`spider` 是加载全部站点用的 jar 包地址**，TVBox 加载配置时先下它，下不到就报 `configure 404` |
| `sites` | **364** 个站点（type 0: 1 / type 1: 51 / type 3: 312）。193 个 `api` 是 http 地址（其中 **只有 52 个是真正的采集站**，其余是 type 3 指向 spider 的代理地址）、5 个带 `jar`、177 个带 `ext`（其中 4 个 ext 是对象） |
| `lives` | 1 组直播，走 `redirect` 代理 |
| `parses` | 26 个解析器（本地 + 第三方聚合） |
| `flags` | 22 个播放器标记 |
| `ijk` | 2 组播放器参数（软解 / 硬解） |
| `ads` | 63 个广告域名黑名单 |
| `rules` | 8 条 m3u8 广告剔除规则 |

站点分两类：
- **type 1**：直接指向采集站的 `api.php` 接口（如 `https://xxzyapi.com/api.php/provide/vod/`）
- **type 3**：走 XYQHiker / XBPQ 等本地爬虫框架，`api` 是框架名、`ext` 指向一个 json 定义文件

## 订阅地址（给 App 用）

**优先推自托管版**，上游删库不影响：

| 用途 | 地址 |
|---|---|
| **自托管 · 推荐** | `https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18-standalone.json` |
| **自托管 · 锁版本** | `https://cdn.jsdelivr.net/gh/ericvlog/tvbox@main/tv18-standalone.json` |
| 上游版（跟 `tvbw/18-` 更新） | `https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18.json` |

**两者取舍**：自托管版扛得住上游删库，但**上游修 bug 你拿不到**，要手动同步；
上游版自动跟进，但上游一删就全废。

## 怎么同步上游更新（自托管版专用）

上游 `tvbw/18-` 改了脚本后，重跑这三步：

```powershell
# 1. 拉上游最新（稀疏克隆，只拉 jar/ 和 tv/）
git clone --depth 1 --filter=blob:none --sparse https://github.com/tvbw/18- $env:TEMP\tvbw-src
git -C $env:TEMP\tvbw-src sparse-checkout set jar tv

# 2. 重建 resources/（按配置里的完整路径名复制，脚本会保持上游原文件名）
node tools\build-resources.mjs $env:TEMP\tvbw-src resources

# 3. 重新生成自托管版
node tools\make-standalone.mjs
```

同步完**必须重跑 URL 实测**（见下面「验证」），确认还是 632/632 通过。

## 历史修复（为什么这份配置长这样）

原配置的 372 处外部引用里，**319 处指向一个已消失的仓库 `wanganni/yinshiyuan`**
（该仓库、该用户本身、gitee / gitcode 镜像**全部 404**），导致 App 加载时报 `configure 404`。

修复方式：
1. 把全部 **325 处**死源引用重定向到同作者仍存活的 `tvbw/18-` 仓库
   （同一套目录结构，1222 个文件 / 229 个 py 脚本，实测 312 个引用全部可达）
2. 修正 `gm.jar` → `GM.jar` 的大小写（上游实际文件名是大写）
3. 删除上游已彻底缺失脚本的 2 个站点（`p115.py`、`Javdb.py`）

**验证方法**：
```powershell
# 1. 死源引用应为 0
(Select-String -Path tv18.json -Pattern "wanganni" -AllMatches).Matches.Count   # → 0
(Select-String -Path tv18-standalone.json -Pattern "tvbw" -AllMatches).Matches.Count   # → 0

# 2. JSON 合法性 + 无 BOM + 纯 LF
node -e "const b=require('fs').readFileSync('tv18-standalone.json');
console.log('BOM:', b[0]===239, 'CR:', b.includes(13), 'valid:', !!JSON.parse(b.toString('utf8')))"

# 3. 全量 URL 实测（最关键，中文/emoji/空格文件名只有实测才算数）
node tools\verify-urls.mjs tv18-standalone.json   # → 可达 632 | 失败 0
```

## 🔧 做这类改动必踩的 8 个坑（本次真实踩过）

1. **「URL 能下载」和「站点能用」是两件不同的事，不要混着讲。**
   `verify-urls.mjs` 测的是本仓库文件能不能下载（632/632 通过），**只等于配置能加载**。
   站点能不能播要跑 `diag-sites.mjs`（364 站点里当下只有 233 个连得上）。
   混着汇报会让人以为「全部都能用」。

1. **用正则从配置里提 URL 会在空格/括号处截断**。
   `[^"'\s\\)]+` 这种模式遇到 `JAV36 (1).py` 只取到 `JAV36`。
   **正确做法**：遍历 JSON 的**完整字符串值**，再用 `lastIndexOf(prefix)` 取后缀。
   本次 12 个文件因此复制成短名，推送后 404，只能再发一次改名 commit。

2. **嵌套 URL 会被漏掉**。直播列表藏在
   `proxy://do=live&type=txt&ext=https://.../tv/做爱大全.txt` 里，
   用 `^https?://` 锚定开头匹配不到，7.8 MB 的直播列表就漏了。

3. **PowerShell `Set-Content -Encoding UTF8` 会写 BOM**（EF BB BF），
   之后 `ConvertFrom-Json` 直接抛异常。**要写无 BOM 文件用
   `[IO.File]::WriteAllBytes()` 或 node 的 `fs.writeFileSync`**。

4. **PowerShell 读文件会加 `\r\n`，写文件会留尾部换行**，导致「明明同一份文件却比对不同」。
   比对要用**字节级**比较，别用字符串。

5. **URL 不能二次编码**。GitHub raw 的中文路径要**按原样**送进 `https.get`，
   手动 `encodeURIComponent` 会把已有的 `%E9%A3%9E` 变成 `%25E9...`，全变 404 假报。
   `gh-proxy.org` 对已编码 URL 还会返回 301。

6. **node 的 `lookup` 覆盖要处理 `all: true`**。`https.get` 内部用 `all: true` 调 lookup，
   直接 `cb(null, ip, 4)` 会抛 `ERR_INVALID_IP_ADDRESS`，看起来像「站连不上」其实是脚本坏了。
   正确写法：`cb(null, o.all ? [{ address: ip, family: 4 }] : ip, 4)`。

7. **TIMEOUT ≠ 死**。马来 ISP 的 DNS 污染会批量制造假 TIMEOUT（见「关键警告」第 1 条）；
   单次超时也可能只是抖动（一个 343 KB 文件首测超时，重测 4 条通道全 200）。
   **删源前必须换真 IP 复测。**

## ⚠️ 关键警告

1. **用户在马来西亚，ISP 做 DNS 污染 —— 这条最容易把判断带错。**
   Time/Unifi/Maxis 等按 MCMC 清单把大量成人域名统一解析到**同一个屏蔽 IP**
   （实测 59 个不相关域名全指向 `175.139.142.25`）。所以「连不上」**大概率不是站死了**。
   判别方法（`tools/diag-sites.mjs` 已实现）：本机 DNS 结果 vs `1.1.1.1` 结果不一致
   → 拿真 IP 直连复测 → 通就是 DNS 污染。**实测证据：同网络换 DNS 后 12/12 全部 200。**
   解法是盒子设私人 DNS `1dot1dot1.cloudflare-dns.com`，值约 45 个源，别去改配置。
   **绝不因为一次 TIMEOUT 就删源。**
2. **自托管 ≠ 什么都能自己维护。** 你**能**维护的是「框架侧」：jar、py 脚本、
   爬虫规则、直播列表（都在 `resources/` 里）。你**不能**维护的是
   **52 个采集站接口**（`xxzyapi.com` 这类 `api.php` 地址）和 312 个爬虫站的**目标站**
   ——它们是第三方站点，挂了只能改配置换源，没法让它们复活。
3. **「配置能加载」≠「每个源都能播放」**。实测（马来西亚本机，2026-11）：
   现在可用 233/364 = 64%，改 DNS 后 278/364 = 76%。**76% 是上限**——只测到目标域连得上，
   爬虫规则是否还匹配当前网页结构测不出来，而「网站改版导致脚本失效」才是爬虫站最常见的死法。
4. **App 内必须先删掉旧配置**（不是覆盖），再**清缓存**，最后重新粘贴订阅地址。
   TVBox 会缓存旧配置和旧 jar，光换地址不够。
5. **版权风险**：`resources/` 里是成人内容的采集脚本与爬虫 jar。GitHub 内容政策
   有可能处理这类内容，公开仓库请自行评估。

## 本机环境（如果你是被 AI 接手）

- **Windows**，PowerShell
- **Python 3.11.4**（注意：低于 3.11 装不了很多现代包）
- **Node v24.12.0**
- **内存 7.9 GB**（装不了 Docker Desktop / torch，别在这台机器上折腾服务端）
- **本机无 `gh` CLI**，用 `curl.exe`（PowerShell 里 `curl` 是 `Invoke-WebRequest` 别名）
- **本地网关 127.0.0.1:8326 活着但要鉴权**（返 401）；10000 端口的 Go 版没启动
- 本机 git credential 里有 `ericvlog` 的 token（`gho_...`），GitHub API 匿名请求会 403 rate limit，
  要用认证请求