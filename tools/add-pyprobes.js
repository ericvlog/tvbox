// 插入两个 py 探针源（raw / gh-proxy），并把 SexKBJ 的 py 源指到修好的 commit。
// 用法：node tools/add-pyprobes.js
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');
const SHA = '698982f';                 // 修好 base.spider 继承后的 commit
const RAW = 'https://raw.githubusercontent.com/ericvlog/tvbox/main/tools';
const PROXY = 'https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tools';

const PROBES = [
  {
    key: 'pyprobe-raw',
    name: 'PY探测(raw)',
    type: 3,
    api: `${RAW}/pyprobe.py`,
    searchable: 0,
    quickSearch: 0,
  },
  {
    key: 'pyprobe-proxy',
    name: 'PY探测(gh-proxy)',
    type: 3,
    api: `${PROXY}/pyprobe.py`,
    searchable: 0,
    quickSearch: 0,
  },
];

const SEXKBJ_API = `https://cdn.jsdelivr.net/gh/ericvlog/tvbox@${SHA}/tools/sexkbj.py`;

function load(p) {
  const buf = fs.readFileSync(p);
  if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) throw new Error('BOM in ' + p);
  return JSON.parse(buf.toString('utf8'));
}

function save(p, obj) {
  const text = JSON.stringify(obj, null, 2) + '\n';
  fs.writeFileSync(p, text, 'utf8');
}

for (const file of ['tv18.json', 'tv18-standalone.json']) {
  const p = path.join(REPO, file);
  const cfg = load(p);
  const before = cfg.sites.length;

  // 去掉旧探针与旧的 sexkbj-py 条目，再统一插回
  cfg.sites = cfg.sites.filter(s => !String(s.key).startsWith('pyprobe') && s.key !== 'sexkbj-py');
  cfg.sites.unshift(...PROBES);
  const py = {
    key: 'sexkbj-py',
    name: 'SexKBJ[韩][py]',
    type: 3,
    api: SEXKBJ_API,
    searchable: 1,
    quickSearch: 1,
  };
  // 放在 spankbang-lan / sexkbj-lan 之后（如果存在）
  const lanIdx = cfg.sites.findIndex(s => s.key === 'sexkbj-lan');
  if (lanIdx >= 0) cfg.sites.splice(lanIdx + 1, 0, py);
  else cfg.sites.push(py);

  save(p, cfg);
  const names = cfg.sites.slice(0, 5).map(s => s.name);
  console.log(`${file}: ${before} -> ${cfg.sites.length} sites | first5 = ${JSON.stringify(names)}`);
  const back = load(p);
  const probe = back.sites.find(s => s.key === 'pyprobe-raw');
  const sk = back.sites.find(s => s.key === 'sexkbj-py');
  console.log(`  pyprobe-raw api = ${probe && probe.api}`);
  console.log(`  sexkbj-py  api = ${sk && sk.api}`);
}
