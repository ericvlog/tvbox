# AGENTS.md — TVBox 项目

> 给接手的 AI 看。这份文件把「这个项目是什么、坑在哪、怎么验证」讲清楚，
> 让另一个 AI 不用重新踩一遍。

## 项目是什么

一份 **TVBox（电视端播放器）的 18+ 内容订阅配置**，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

- **`tv18.json`** —— 主配置文件（153 KB，合法 JSON，无 BOM）
- **`README.md`** —— 人类可读的说明

## 配置结构（tv18.json 顶层字段）

| 字段 | 内容 |
|---|---|
| `wallpaper` / `spider` / `logo` / `warningText` | 元信息。**`spider` 是加载全部站点用的 jar 包地址**，TVBox 加载配置时先下它，下不到就报 `configure 404` |
| `sites` | **364** 个站点。193 个带外部 `api`、5 个带 `jar`、172 个带 `ext` |
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

| 用途 | 地址 |
|---|---|
| **推荐（走代理，国内稳）** | `https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18.json` |
| **锁版本（绕 CDN 缓存）** | `https://cdn.jsdelivr.net/gh/ericvlog/tvbox@main/tv18.json` |

## 历史修复（为什么这份配置长这样）

原配置的 372 处外部引用里，**319 处指向一个已消失的仓库 `wanganni/yinshiyuan`**
（该仓库、该用户本身、gitee / gitcode 镜像**全部 404**），导致 App 加载时报 `configure 404`。

修复方式：
1. 把全部 **325 处**死源引用重定向到同作者仍存活的 `tvbw/18-` 仓库
   （同一套目录结构，1222 个文件 / 229 个 py 脚本，实测 312 个引用全部可达）
2. 修正 `gm.jar` → `GM.jar` 的大小写（上游实际文件名是大写）
3. 删除上游已彻底缺失脚本的 2 个站点（`p115.py`、`Javdb.py`）

**验证方法**：`grep -c wanganni tv18.json` 应为 **0**；
`python -c "import json; json.load(open('tv18.json'))"` 应能正常解析。

## ⚠️ 关键警告

1. **「配置能加载」≠「每个源都能播放」**。上游 91 个主机里 **49 个已死**
   （超时 / 解析失败 / 404），活着的多是采集接口。源的可用性取决于上游采集站是否还活着，
   跟这份配置本身无关。
2. **App 内必须先删掉旧配置**（不是覆盖），再**清缓存**，最后重新粘贴订阅地址。
   TVBox 会缓存旧配置和旧 jar，光换地址不够。
3. **配置里全是 18+ 内容**，分享或提交时注意场合。

## 本机环境（如果你是被 AI 接手）

- **Windows**，PowerShell
- **Python 3.11.4**（注意：低于 3.11 装不了很多现代包）
- **Node v24.12.0**
- **内存 7.9 GB**（装不了 Docker Desktop / torch，别在这台机器上折腾服务端）
- **本机无 `gh` CLI**，用 `curl.exe`（PowerShell 里 `curl` 是 `Invoke-WebRequest` 别名）
- **本地网关 127.0.0.1:8326 活着但要鉴权**（返 401）；10000 端口的 Go 版没启动
- 本机 git credential 里有 `ericvlog` 的 token（`gho_...`），GitHub API 匿名请求会 403 rate limit，
  要用认证请求