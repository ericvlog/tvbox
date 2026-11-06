// 重建 resources/ —— 按 tv18-standalone.json 里引用的完整路径，从上游克隆复制过来
// 用法: node tools/build-resources.mjs <上游克隆目录> <输出目录>
//   node tools/build-resources.mjs $env:TEMP/tvbw-src resources
import fs from 'fs';
import path from 'path';

const srcRoot = process.argv[2] || path.join(process.env.TEMP || '/tmp', 'tvbw-src');
const dstRoot = process.argv[3] || 'resources';
const CFG = 'tv18.json';

if (!fs.existsSync(path.join(srcRoot, 'tv'))) {
  console.error('上游克隆缺 tv/ 目录，先跑:\n  git clone --depth 1 --filter=blob:none --sparse https://github.com/tvbw/18- ' + srcRoot +
    '\n  git -C ' + srcRoot + ' sparse-checkout set jar tv');
  process.exit(1);
}

const j = JSON.parse(fs.readFileSync(CFG, 'utf8'));
const PRE = 'tvbw/18-/refs/heads/main/';
const PRE2 = 'tvbw/18-/main/';

// 关键: 遍历 JSON 的完整字符串值, 用 lastIndexOf 取后缀。
// 不要用正则从原文提 URL —— 会在空格/括号处截断(JAV36 (1).py -> JAV36)。
const upstreamPaths = new Set();
(function walk(o) {
  if (typeof o === 'string') {
    for (const p of [PRE, PRE2]) {
      const i = o.lastIndexOf(p);
      if (i >= 0) {
        let rel = o.slice(i + p.length);
        try { rel = decodeURIComponent(rel); } catch {}
        if (rel) upstreamPaths.add(rel);
      }
    }
    return;
  }
  if (Array.isArray(o)) { o.forEach(walk); return; }
  if (o && typeof o === 'object') Object.values(o).forEach(walk);
})(j);

const list = [...upstreamPaths].sort();

// 索引上游真实文件
const upstream = new Set();
(function walkDir(dir, prefix) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, e.name);
    if (e.isDirectory()) walkDir(full, prefix + e.name + '/');
    else upstream.add(prefix + e.name);
  }
})(path.join(srcRoot, 'jar'), 'jar/');
{
  function w2(dir, prefix) {
    for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, e.name);
      if (e.isDirectory()) w2(full, prefix + e.name + '/');
      else upstream.add(prefix + e.name);
    }
  }
  w2(path.join(srcRoot, 'tv'), 'tv/');
}

console.log('配置引用的上游文件:', list.length);
const missing = list.filter(p => !upstream.has(p));
console.log('上游不存在的:', missing.length);
missing.slice(0, 10).forEach(p => console.log('  NOT FOUND', p));

fs.rmSync(dstRoot, { recursive: true, force: true });
let copied = 0, bytes = 0;
for (const p of list) {
  if (!upstream.has(p)) continue;
  const dst = path.join(dstRoot, p);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  const buf = fs.readFileSync(path.join(srcRoot, p));
  fs.writeFileSync(dst, buf);          // 用上游原文件名, 不要自己拼
  copied++; bytes += buf.length;
}
console.log('已复制:', copied, '个文件,', (bytes / 1024 / 1024).toFixed(1), 'MB');
if (missing.length) console.log('⚠ 有 ' + missing.length + ' 个引用在上游找不到, 对应站点需要手动删或改');