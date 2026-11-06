# TVBox 配置项目

一份 TVBox（TV 盒子/电视端播放器）的 18+ 内容订阅配置，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

## 文件

| 文件 | 说明 |
|---|---|
| **`tv18.json`** | 主配置（364 站点）。脚本/jar 从**上游 `tvbw/18-`** 加载 |
| **`tv18-standalone.json`** | **自托管版**。同样的 364 站点，脚本/jar 全部从**本仓库 `resources/`** 加载 |
| `resources/` | 316 个上游文件副本（14.6 MB）：jar、py 脚本、XYQHiker/XBPQ 定义、直播列表 |
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

## ⚠️ 三个必须知道的事

1. **自托管 ≠ 什么都能自己维护。** 你能维护的是「框架侧」——jar、py 脚本、爬虫规则、
   直播列表。而配置里 **193 个采集站接口**（`xxzyapi.com` 这类 `api.php` 地址）是
   **第三方站点，不在本仓库里**，它们挂了只能改配置换源，你没法让它们复活。
2. **「配置能加载」≠「每个源都能播放」。** 上游 91 个主机里 **49 个已死**。
3. **App 内必须先删掉旧配置**（不是覆盖）→ **清缓存** → 再粘贴新地址。
   否则 TVBox 会一直用缓存里的旧配置和旧 jar。

## 历史：原来为什么报 configure 404

原配置 372 处外部引用里 **319 处**指向已消失的仓库 `wanganni/yinshiyuan`
（该仓库、该用户、gitee / gitcode 镜像**全部 404**）。TVBox 加载配置时先下 `spider`
指定的 jar，下不到就报错。修复：325 处重定向到 `tvbw/18-`、`gm.jar`→`GM.jar`
大小写修正、删除上游已彻底缺失脚本的 2 个站点。