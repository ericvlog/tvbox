#!/usr/bin/env node
/**
 * update-gateway-ip.mjs — 网关换了内网 IP 时，自动改配置并（可选）推送。
 *
 * 现在有两个本机网关源：
 *   spankbang-lan  -> http://<IP>:8080/api.php/provide/vod/
 *   sexkbj-lan     -> http://<IP>:8081/api.php/provide/vod/
 *
 * 用手机热点上网，IP 每次都不一样，手改容易漏。
 *
 * 用法：
 *   node tools/update-gateway-ip.mjs                     # 只检测 + 改本地文件
 *   node tools/update-gateway-ip.mjs --push              # 改完自动 commit + push
 *   node tools/update-gateway-ip.mjs --set 192.168.43.7  # 跳过探测，直接指定 IP
 *   node tools/update-gateway-ip.mjs --only sexkbj-lan   # 只处理一个源
 *
 * 退出码：0 = 无需改动或已更新；1 = 找不到可用 IP / 出错。
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';

const TARGETS = [
  { key: 'spankbang-lan', port: 8080, site: 'spankbang-gateway' },
  { key: 'sexkbj-lan', port: 8081, site: 'sexkbj-gateway' },
  { key: 'erome-lan', port: 8082, site: 'erome-gateway' },
];
const CONFIGS = ['tv18.json', 'tv18-standalone.json'];

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const value = (name, dflt) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};

const PUSH = flag('--push');
const SET = value('--set', null);
const ONLY = value('--only', null);
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

async function probe(ip, port, site, timeoutMs = 2500) {
  try {
    const res = await fetch(`http://${ip}:${port}/`, { signal: AbortSignal.timeout(timeoutMs) });
    if (!res.ok) return false;
    const body = await res.json().catch(() => null);
    return !!body && body.site === site;
  } catch {
    return false;
  }
}

async function findIp(t) {
  if (SET) {
    if (!(await probe(SET, t.port, t.site))) {
      console.error(`[!] ${t.key}: 指定的 ${SET}:${t.port} 打不通（网关没启动？防火墙没放行？）`);
      return null;
    }
    return SET;
  }
  const list = candidates();
  if (!list.length) {
    console.error('[!] 没有任何非回环 IPv4 地址');
    return null;
  }
  for (const { ip } of list) {
    if (await probe(ip, t.port, t.site)) return ip;
  }
  console.error(`[!] ${t.key}: 没有地址能在 ${t.port} 上应答。先启动网关，并确认防火墙放行 ${t.port}。`);
  return null;
}

function rewrite(t, ip) {
  const api = `http://${ip}:${t.port}/api.php/provide/vod/`;
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
    // 允许文件末尾多/少一个换行：只校验主体是 2 空格缩进
    const body = text.replace(/\n+$/, '');
    if (JSON.stringify(obj, null, 2) !== body) {
      throw new Error(`${file} 不是 2 空格缩进的规范 JSON，拒绝重写（会放大 diff）`);
    }
    const trailing = text.endsWith('\n') ? '\n' : '';
    const site = (obj.sites || []).find((s) => s && s.key === t.key);
    if (!site) {
      console.warn(`[!] ${file} 里没有 ${t.key}，跳过`);
      continue;
    }
    if (site.api === api) {
      console.log(`[=] ${t.key} ${file}: 已是 ${api}`);
      continue;
    }
    console.log(`[~] ${t.key} ${file}: ${site.api}  ->  ${api}`);
    site.api = api;
    fs.writeFileSync(p, JSON.stringify(obj, null, 2) + trailing, 'utf8');
    changed.push(file);
  }
  return { api, changed };
}

function gitPush(changed, summary) {
  const run = (args) => execFileSync('git', args, { cwd: root, stdio: 'pipe' }).toString().trim();
  const dirty = run(['status', '--porcelain', '--', ...new Set(changed)]);
  if (!dirty) {
    console.log('[=] 文件内容与已提交版本一致，无需提交');
    return null;
  }
  run(['add', ...new Set(changed)]);
  run(['commit', '-m', `Point gateway sites at ${summary}\n\n本机网关内网 IP 变了（手机热点 DHCP），自动更新。`]);
  execFileSync('git', ['push', 'origin', 'HEAD'], { cwd: root, stdio: 'pipe' });
  console.log('[>] 提交:', run(['log', '--oneline', '-1']));
  return run(['log', '--oneline', '-1']);
}

const targets = ONLY ? TARGETS.filter((t) => t.key === ONLY) : TARGETS;
if (!targets.length) {
  console.error(`[!] 未知的 --only 值，可选：${TARGETS.map((t) => t.key).join(', ')}`);
  process.exit(1);
}

const changed = [];
const hosts = [];
let failed = false;

for (const t of targets) {
  const ip = await findIp(t);
  if (!ip) {
    failed = true;
    continue;
  }
  console.log(`[*] ${t.key} -> ${ip}:${t.port}`);
  const { api, changed: files } = rewrite(t, ip);
  changed.push(...files);
  hosts.push(`${t.key}=${new URL(api).host}`);
}

if (!changed.length) {
  console.log(failed ? '[!] 有网关没应答，但配置无需改动。' : '[=] 配置无需改动。');
  process.exit(failed ? 1 : 0);
}

if (PUSH) {
  try {
    gitPush(changed, hosts.join(' '));
    console.log('\n[✓] 已推送。App 里刷新订阅（或删配置重加）即可生效。');
  } catch (e) {
    console.error('[!] push 失败：', e.stderr ? e.stderr.toString() : e.message);
    process.exit(1);
  }
} else {
  console.log('\n[✓] 本地已改。要发布请加 --push。');
}
