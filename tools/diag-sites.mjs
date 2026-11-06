// 站点可用性体检 —— 区分"真死了"和"只是被 ISP 的 DNS 屏蔽"
// 用法: node tools/diag-sites.mjs [配置文件] [并发数]
//   node tools/diag-sites.mjs tv18-standalone.json
//
// 为什么要这个脚本: 马来西亚/新加坡等地 ISP 按 MCMC 清单做 DNS 污染, 把一堆成人
// 域名统一解析到同一个屏蔽 IP。这些站其实活着, 换 DNS 就能用。只看"连不上就删"
// 会误杀近百个源。判别方法: 本机 DNS 与 1.1.1.1 结果不一致 -> 用真 IP 直连复测。
import fs from 'fs';
import path from 'path';
import http from 'http';
import https from 'https';
import dns from 'dns';

const CFG = process.argv[2] || 'tv18-standalone.json';
const PAR = Number(process.argv[3] || 16);
const ROOT = process.cwd();

const j = JSON.parse(fs.readFileSync(CFG, 'utf8'));

// ---------- 取每个站点的真实目标 ----------
// type 0/1: api 就是采集站地址。type 3: api 是框架名, 目标域在它引用的定义文件里
const INFRA = /githubusercontent\.com|gh-proxy|jsdelivr|googleapis|gstatic|w3\.org|example|localhost|127\.0\.0\.1|doubleclick|googletagmanager|googlesyndication|adsco|magsrv|pemsrv|tsyndicate|mnaspm|hpyjmp|tapioni|shukriya90|imkirh|xlvirdr|cnzz|qhimg|qhimgs|baidu\.com/;

function resPath(s) {
  for (const c of [s.ext, s.api, s.jar].filter(v => typeof v === 'string')) {
    const i = c.lastIndexOf('ericvlog/tvbox/main/');
    if (i < 0) continue;
    let rel = c.slice(i + 'ericvlog/tvbox/main/'.length);
    try { rel = decodeURIComponent(rel); } catch {}
    if (/\.(json|py|js|txt)$/i.test(rel)) return rel;   // 已含 resources/ 前缀
  }
  if (s.ext && typeof s.ext === 'object') {
    const m = JSON.stringify(s.ext).match(/ericvlog\/tvbox\/main\/([^"\\]+)/);
    if (m) { try { return decodeURIComponent(m[1]); } catch { return m[1]; } }
  }
  return null;
}
function hostsOf(text) {
  const out = [];
  for (const m of text.matchAll(/https?:\/\/([a-zA-Z0-9][a-zA-Z0-9.-]*\.[a-z]{2,})(?::\d+)?/gi)) {
    const h = m[1].toLowerCase();
    if (!INFRA.test(h)) out.push(h);
  }
  return [...new Set(out)];
}

const jobs = [];
const noTarget = [];
for (const s of j.sites) {
  if (s.type === 0 || s.type === 1) {
    if (typeof s.api === 'string' && /^https?:/.test(s.api)) {
      jobs.push({ name: s.name, kind: 'CMS', url: s.api, host: new URL(s.api).host });
    } else noTarget.push(s.name);
    continue;
  }
  const rel = resPath(s);
  if (!rel) { noTarget.push(s.name); continue; }
  let text;
  try { text = fs.readFileSync(path.join(ROOT, rel), 'utf8'); } catch { noTarget.push(s.name + ' [读不到]'); continue; }
  const hs = hostsOf(text);
  if (!hs.length) { noTarget.push(s.name + ' [无外部域名]'); continue; }
  jobs.push({ name: s.name, kind: 'CRAWLER', url: 'https://' + hs[0] + '/', host: hs[0] });
}
console.log('站点总数:', j.sites.length, '| 可测:', jobs.length, '| 无固定域名(本地/聚合):', noTarget.length);

// ---------- 探测 ----------
const sys = new dns.Resolver();
const dohR = new dns.Resolver({ timeout: 6000, tries: 2 }); dohR.setServers(['1.1.1.1', '1.0.0.1']);
const res4 = (r, h) => new Promise(k => r.resolve4(h, (e, a) => k(e ? [] : a)));

function get(url, ip, ms = 12000) {
  return new Promise((res) => {
    const u = new URL(url);
    const lib = u.protocol === 'https:' ? https : http;
    const opt = {
      timeout: ms, headers: { 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36', 'Accept-Language': 'zh-CN,zh;q=0.9' },
      rejectUnauthorized: false, servername: u.hostname
    };
    if (ip) opt.lookup = (h, o, cb) => cb(null, (o && o.all) ? [{ address: ip, family: 4 }] : ip, 4);
    const req = lib.get(url, opt, r => { r.resume(); r.on('end', () => res(r.statusCode)); r.on('error', () => res(r.statusCode || 'ERR')); });
    req.on('timeout', () => { req.destroy(); res('TIMEOUT'); });
    req.on('error', e => res(e.code || 'ERR'));
  });
}
const httpOk = st => (typeof st === 'number' && st < 500) || st === 403 || st === 406;

async function test(job) {
  const base = job.kind === 'CMS'
    ? job.url + (/[?&]ac=/.test(job.url) ? '' : (job.url.includes('?') ? '&' : '?') + 'ac=list')
    : job.url;
  const first = await get(base);
  if (httpOk(first)) return { ...job, verdict: job.kind === 'CMS' ? 'ALIVE' : 'REACHABLE', via: 'system-dns' };

  // 连不上 -> 用 1.1.1.1 重新解析, 拿真 IP 再试
  const real = await res4(dohR, job.host);
  const mine = await res4(sys, job.host);
  if (!real.length) return { ...job, verdict: 'DOMAIN_GONE', why: '真死: 域名已注销(DoH 也解不出)', via: 'doh' };
  if (!mine.length) {
    const st = await get(base, real[0]);
    return httpOk(st) ? { ...job, verdict: 'DNS_BLOCKED', why: 'ISP 不给解析, 换 DNS 即可', ip: real[0] }
      : { ...job, verdict: 'DEAD?', why: 'DNS 屏蔽且真 IP 也连不上(' + st + ')', ip: real[0] };
  }
  if (!mine.some(ip => real.includes(ip))) {
    const st = await get(base, real[0]);
    return httpOk(st) ? { ...job, verdict: 'DNS_BLOCKED', why: 'ISP 返回假 IP(屏蔽页), 换 DNS 即可', ip: real[0], fakeIp: mine[0] }
      : { ...job, verdict: 'DEAD?', why: 'DNS 被污染且真 IP 连不上(' + st + ')', ip: real[0] };
  }
  return { ...job, verdict: (first === 'TIMEOUT' ? 'TIMEOUT' : 'HTTP_' + first), why: 'DNS 正常但服务异常', ip: mine[0] };
}

const rows = [];
let i = 0;
async function w() { while (i < jobs.length) rows.push(await test(jobs[i++])); }
await Promise.all(Array.from({ length: PAR }, w));

const cnt = {};
rows.forEach(r => cnt[r.verdict] = (cnt[r.verdict] || 0) + 1);
console.log('\n=== 体检结果 ===');
Object.entries(cnt).sort((a, b) => b[1] - a[1]).forEach(([k, v]) => console.log('  ' + k.padEnd(14) + v));
console.log('  NO_TARGET     ' + noTarget.length);

const now = rows.filter(r => ['ALIVE', 'REACHABLE'].includes(r.verdict)).length;
const byDns = rows.filter(r => r.verdict === 'DNS_BLOCKED').length;
const dead = rows.filter(r => ['DOMAIN_GONE', 'DEAD?', 'PORT_CLOSED'].includes(r.verdict));
console.log('\n现在就可用        : ' + now + '/' + j.sites.length + ' = ' + Math.round(now / j.sites.length * 100) + '%');
console.log('换 DNS 额外救回   : ' + byDns);
console.log('修好 DNS 后可用   : ' + (now + byDns) + '/' + j.sites.length + ' = ' + Math.round((now + byDns) / j.sites.length * 100) + '%');
console.log('建议删除          : ' + dead.length);

const outFile = path.join(ROOT, 'diag-result.json');
fs.writeFileSync(outFile, JSON.stringify({ at: new Date().toISOString(), cfg: CFG, rows, noTarget }, null, 1));
console.log('\n明细 -> ' + outFile);
if (dead.length) {
  console.log('\n--- 建议删除(真死) ---');
  dead.slice(0, 40).forEach(r => console.log('  ' + r.verdict.padEnd(10) + r.host.padEnd(26) + r.name.slice(0, 30)));
}
if (byDns) {
  console.log('\n⚠ ' + byDns + ' 个站是被本机 DNS 屏蔽的, 不是坏了。');
  console.log('  Android TV: 设置 -> 网络 -> 私人DNS(Private DNS) -> 主机名填 1dot1dot1dot1.cloudflare-dns.com');
  console.log('  或在路由器上把 DNS 改成 1.1.1.1 / 8.8.8.8');
}
