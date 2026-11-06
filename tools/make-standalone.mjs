// 由 tv18.json 生成 tv18-standalone.json —— 把所有上游引用改指向本仓库 resources/
// 用法: node tools/make-standalone.mjs [输出文件]
import fs from 'fs';

const OUT = process.argv[2] || 'tv18-standalone.json';
const ME = 'ericvlog/tvbox/main/';

let raw = fs.readFileSync('tv18.json', 'utf8');

// 按长度降序替换, 避免短路径先吃掉长路径的前缀
const PRE = 'tvbw/18-/refs/heads/main/';
const PRE2 = 'tvbw/18-/main/';
const paths = new Set();
(function walk(o) {
  if (typeof o !== 'string') {
    if (Array.isArray(o)) o.forEach(walk);
    else if (o && typeof o === 'object') Object.values(o).forEach(walk);
    return;
  }
  for (const p of [PRE, PRE2]) {
    const i = o.lastIndexOf(p);
    if (i >= 0) {
      let rel = o.slice(i + p.length);
      try { rel = decodeURIComponent(rel); } catch {}
      if (rel) paths.add(rel);
    }
  }
})(JSON.parse(raw));

const esc = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
let hits = 0;
for (const p of [...paths].sort((a, b) => b.length - a.length)) {
  for (const pre of [PRE, PRE2]) {
    const re = new RegExp(esc(pre + p), 'g');
    raw = raw.replace(re, () => { hits++; return ME + 'resources/' + p; });
  }
}
console.log('重写:', hits, '处 | 涉及', paths.size, '个文件');

const left = (raw.match(/tvbw/g) || []).length;
if (left) { console.error('⚠ 还剩 ' + left + ' 处 tvbw 引用未替换, 检查上面的路径提取'); process.exit(1); }

const j = JSON.parse(raw);                      // 不合法就直接抛
if (raw.includes('\r')) console.error('⚠ 含 CR, TVBox 侧解析可能受影响');
if (raw.charCodeAt(0) === 0xFEFF) console.error('⚠ 含 BOM');
fs.writeFileSync(OUT, Buffer.from(raw, 'utf8')); // 无 BOM
console.log('写出', OUT, '| sites:', j.sites.length, '| 大小:', Buffer.byteLength(raw), 'bytes');