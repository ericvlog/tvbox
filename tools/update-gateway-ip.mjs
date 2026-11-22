#!/usr/bin/env node
/**
 * update-gateway-ip.mjs — 网关换了内网 IP 时，自动改配置并（可选）推送。
 *
 * 背景：配置里的 `spankbang-lan` 源指向本机网关（http://<内网IP>:8080/...）。
 * 用手机热点上网，IP 每次都不一样，手改容易漏。
 *
 * 用法：
 *   node tools/update-gateway-ip.mjs                     # 只检测 + 改本地文件
 *   node tools/update-gateway-ip.mjs --port 8080
 *   node tools/update-gateway-ip.mjs --push              # 改完自动 commit + push
 *   node tools/update-gateway-ip.mjs --set 192.168.43.7  # 跳过探测，直接指定
 *
 * 退出码：0 = 无需改动或已更新；1 = 找不到可用 IP / 出错。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const KEY = 'spankbang-lan';
const CONFIGS = ['tv18.json', 'tv18-standalone.json'];

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const value = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};

const PORT = Number(value('--port', 8080));
const PUSH = flag('--push');
const SET = value('--set', null);
const root = path.resolve(path.dirname(new URL(import.meta.url).pathname.replace(/^\//, '')), '..');

function candidates() {
  const out = [];
  for (const [name, addrs] of Object.entries(os.networkInterfaces())) {
    for (const a of addrs || []) {
      if (a.family !== 'IPv4' || a.internal) continue;
      if (a.address.startsWith('169.254.')) continue;
      out.push({ iface: name, ip: a.address });
    }
  }
  return out;
}

async function probe(ip, timeoutMs = 2500) {
  const url = `http://${ip}:${PORT}/`;
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) });
    if (!res.ok) return false;
    const body = await res.json().catch(() => null);
    return !!body && body.site === 'spankbang-gateway';
  } catch {
    return false;
  }
}

async function findIp() {
  if (SET) {
    if (!(await probe(SET))) {
      console.error(`[!] 指定的 ${SET}:${PORT} 打不通（网关没启动？防火墙没放行？）`);
      return null;
    }
    return SET;
  }
  const list = candidates();
  if (!list.length) {
    console.error('[!] 没有任何非回环 IPv4 地址');
    return null;
  }
  console.log(`[*] 探测 ${list.length} 个候选地址 ...`);
  for (const { iface, ip } of list) {
    const ok = await probe(ip);
    console.log(`    ${ok ? 'OK  ' : '  - '} ${ip.padEnd(16)} ${iface}`);
    if (ok) return ip;
  }
  console.error(`[!] 没有地址能在 ${PORT} 上应答。先启动网关（start.cmd），并确认防火墙放行 ${PORT}。`);
  return null;
}

function rewrite(ip) {
  const api = `http://${ip}:${PORT}/api.php/provide/vod/`;
  const changed = [];
  for (const file of CONFIGS) {
    const p = path.join(root, file);
    if (!fs.existsSync(p)) {
      console.warn(`[!] 跳过（不存在）：${file}`);
      continue;
    }
    const raw = fs.readFileSync(p);
    if (raw[0] === 0xef) throw new Error(`${file} 带 BOM，拒绝处理`);
    const text = raw.toString('utf8');
    const obj = JSON.parse(text);
    if (JSON.stringify(obj, null, 2) !== text) {
      throw new Error(`${file} 不是 2 空格缩进的规范 JSON，拒绝重写（会放大 diff）`);
    }
    const site = (obj.sites || []).find((s) => s && s.key === KEY);
    if (!site) {
      console.warn(`[!] ${file} 里没有 ${KEY}，跳过`);
      continue;
    }
    if (site.api === api) {
      console.log(`[=] ${file}: 已是 ${api}`);
      continue;
    }
    console.log(`[~] ${file}: ${site.api}  ->  ${api}`);
    site.api = api;
    fs.writeFileSync(p, JSON.stringify(obj, null, 2), 'utf8');
    changed.push(file);
  }
  return { api, changed };
}

function gitPush(changed, api) {
  const run = (args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' }).toString().trim();
  run(['add', ...changed]);
  const msg = `Point gateway site at ${new URL(api).host}\n\n本机网关内网 IP 变了（手机热点 DHCP），自动更新 ${KEY}.api。`;
  run(['commit', '-m', msg]);
  const out = execFileSync('git', ['push', 'origin', 'HEAD'], { cwd: root, stdio: 'pipe' });
  console.log('[>] push:', out.toString().trim() || 'ok');
  console.log('[>] 提交:', run(['log', '--oneline', '-1']));
}

const ip = await findIp();
if (!ip) process.exit(1);

const { api, changed } = rewrite(ip);

if (!changed.length) {
  console.log('[=] 配置无需改动。');
  process.exit(0);
}

if (PUSH) {
  try {
    gitPush(changed, api);
    console.log('\n[✓] 已推送。App 里下拉刷新订阅（或删配置重加）即可生效。');
  } catch (e) {
    console.error('[!] push 失败：', e.stderr ? e.stderr.toString() : e.message);
    process.exit(1);
  }
} else {
  console.log('\n[✓] 本地已改。要发布请加 --push。');
}
