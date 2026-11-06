# TVBox 配置项目

一份 TVBox（TV 盒子/电视端播放器）的 18+ 内容订阅配置，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

## 文件

| 文件 | 说明 |
|---|---|
| **`tv18.json`** | 主配置（364 站点）。脚本/jar 从**上游 `tvbw/18-`** 加载 |
| **`tv18-standalone.json`** | **自托管版**。同样的 364 站点，脚本/jar 全部从**本仓库 `resources/`** 加载 |
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

## 历史：原来为什么报 configure 404

原配置 372 处外部引用里 **319 处**指向已消失的仓库 `wanganni/yinshiyuan`
（该仓库、该用户、gitee / gitcode 镜像**全部 404**）。TVBox 加载配置时先下 `spider`
指定的 jar，下不到就报错。修复：325 处重定向到 `tvbw/18-`、`gm.jar`→`GM.jar`
大小写修正、删除上游已彻底缺失脚本的 2 个站点。