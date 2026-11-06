# TVBox 配置项目

## 这是什么

一份 TVBox（TV 盒子/电视端播放器）的 18+ 内容订阅配置，已修复并托管在
[ericvlog/tvbox](https://github.com/ericvlog/tvbox) 的 `main` 分支。

## 文件

- **`tv18.json`** —— 主配置文件（364 个站点 + 蜘蛛 jar + 直播列表 + logo）

## 订阅地址

| 用途 | 地址 |
|---|---|
| **推荐（走代理，国内稳）** | `https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tv18.json` |
| **锁版本（绕 CDN 缓存）** | `https://cdn.jsdelivr.net/gh/ericvlog/tvbox@main/tv18.json` |

## 修复内容

原配置的 372 处外部引用里，319 处指向一个已消失的仓库 `wanganni/yinshiyuan`（该仓库、
该用户、gitee / gitcode 镜像全部 404），导致 App 加载时报 `configure 404`。

修复方式：把全部 325 处死源引用重定向到同作者仍存活的 `tvbw/18-` 仓库
（同一套目录结构，1222 个文件 / 229 个 py 脚本，实测 312 个引用全部可达），
并修正 `gm.jar` → `GM.jar` 的大小写，删除上游已彻底缺失脚本的 2 个站点。

## 使用前提

- App 内**必须先删掉旧配置**（不是覆盖），再**清缓存**，最后重新粘贴订阅地址。
- 顺手扫描过全部 91 个上游主机，**49 个已死**（超时/解析失败/404）。
  **「配置能加载」≠「每个源都能播放」**，源的可用性取决于上游采集站是否还活着。