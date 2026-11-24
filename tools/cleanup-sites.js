// 清理配置：删掉临时 py 探针、给网关/py 源指定海报墙版式、把 py 源 pin 到最新 commit。
// 用法：node tools/cleanup-sites.js
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const SHA = process.argv[2] || 'c65157e';
const PY_API = `https://cdn.jsdelivr.net/gh/ericvlog/tvbox@${SHA}/tools/sexkbj.py`;

const DROP_KEYS = ['pyprobe-raw', 'pyprobe-proxy', 'pyprobe'];
const GRID_KEYS = ['spankbang-lan', 'sexkbj-lan', 'sexkbj-py'];

function load(p) {
  const buf = fs.readFileSync(p);
  if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) throw new Error('BOM in ' + p);
  return JSON.parse(buf.toString('utf8'));
}

for (const file of ['tv18.json', 'tv18-standalone.json']) {
  const p = path.join(REPO, file);
  const cfg = load(p);
  const before = cfg.sites.length;

  cfg.sites = cfg.sites.filter(s => !DROP_KEYS.includes(s.key));

  for (const s of cfg.sites) {
    if (GRID_KEYS.includes(s.key)) s.style = 'grid';   // 海报墙，别让它退化成一行一行的列表
    if (s.key === 'sexkbj-py') {
      s.name = 'SexKBJ[韩]';
      s.api = PY_API;
      s.searchable = 1;
      s.quickSearch = 1;
    }
  }

  fs.writeFileSync(p, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
  console.log(`${file}: ${before} -> ${cfg.sites.length} sites`);
  for (const s of cfg.sites.slice(0, 4)) {
    console.log(`   ${s.key} | ${s.name} | type ${s.type} | style ${s.style || '-'} | ${String(s.api).slice(0, 60)}`);
  }
}
