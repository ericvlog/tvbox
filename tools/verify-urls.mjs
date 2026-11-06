// 全量实测配置里每个 URL 能否取到 —— 中文/emoji/空格文件名只有实测才算数
// 用法: node tools/verify-urls.mjs [配置文件] [并发数]
import fs from 'fs';
import https from 'https';

const CFG = process.argv[2] || 'tv18-standalone.json';
const PAR = Number(process.argv[3] || 10);

const j = JSON.parse(fs.readFileSync(CFG, 'utf8'));

// 遍历完整字符串值。正则 [^\s]+ 会在空格处截断(JAV36 (1).py -> JAV36),
// 所以这里先定位 URL 起点, 再直接切到字符串末尾 —— JSON 字符串值内部不含裸引号, 安全。
// 同时覆盖 proxy://...&ext=https://... 这种嵌套形式。
const urls = new Set();
(function walk(o) {
  if (typeof o === 'string') {
    for (const pre of ['https://', 'http://']) {
      let from = 0;
      for (;;) {
        const i = o.indexOf(pre, from);
        if (i < 0) break;
        urls.add(o.slice(i).trim());
        from = i + pre.length;
      }
    }
    return;
  }
  if (Array.isArray(o)) { o.forEach(walk); return; }
  if (o && typeof o === 'object') Object.values(o).forEach(walk);
})(j);

const mine = [...urls].filter(u => u.includes('ericvlog/tvbox'));
console.log('本仓库 URL:', mine.length, '| 配置内 URL 总数:', urls.size);

function probe(u, ms = 15000) {
  return new Promise((res) => {
    // 原样送: GitHub raw 的中文路径已是明文, 二次 encodeURIComponent 会变
    // %25E9... 全部 404。gh-proxy.org 对已编码 URL 还会回 301。
    const req = https.get(u, { timeout: ms, headers: { 'User-Agent': 'okhttp/4.9.2' } }, (r) => {
      let n = 0; r.on('data', c => n += c.length);
      r.on('end', () => res({ st: r.statusCode, n }));
      r.on('error', () => res({ st: r.statusCode || 'ERR', n: 0 }));
    });
    req.on('timeout', () => { req.destroy(); res({ st: 'TIMEOUT', n: 0 }); });
    req.on('error', (e) => res({ st: e.code || 'ERR', n: 0 }));
  });
}

let ok = 0; const fails = [];
let i = 0;
async function worker() {
  while (i < mine.length) {
    const u = mine[i++];
    const r = await probe(u);
    if (r.st === 200 && r.n > 0) ok++;
    else fails.push(r.st + ' bytes=' + r.n + ' ' + u);
  }
}
await Promise.all(Array.from({ length: PAR }, worker));

console.log('可达(200 且有内容):', ok, '| 失败:', fails.length);
fails.slice(0, 20).forEach(f => console.log('  FAIL', f));
process.exit(fails.length ? 1 : 0);