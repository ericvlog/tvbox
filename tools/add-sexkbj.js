// 往 tv18.json / tv18-standalone.json 里插入 SexKBJ py 源（幂等）
const fs = require("fs");

const ENTRY = {
  key: "sexkbj-py",
  name: "SexKBJ[韩]",
  type: 3,
  api: "https://gh-proxy.org/https://raw.githubusercontent.com/ericvlog/tvbox/main/tools/sexkbj.py",
  searchable: 1,
  quickSearch: 1,
};

const files = process.argv.slice(2);
if (!files.length) {
  console.error("usage: node add-sexkbj.js <json...>");
  process.exit(2);
}

for (const f of files) {
  const buf = fs.readFileSync(f);
  if (buf[0] === 0xef && buf[1] === 0xbb && buf[2] === 0xbf) {
    console.error("SKIP (has BOM):", f);
    process.exit(1);
  }
  const text = buf.toString("utf8");
  const obj = JSON.parse(text);
  if (JSON.stringify(obj, null, 2) !== text) {
    console.error("ABORT (formatting not 2-space):", f);
    process.exit(1);
  }
  const before = obj.sites.length;
  obj.sites = obj.sites.filter((s) => s.key !== ENTRY.key);
  // 放在网关源后面，保持「本机源在前」的顺序
  const idx = obj.sites.findIndex((s) => s.key === "spankbang-lan");
  obj.sites.splice(idx >= 0 ? idx + 1 : 0, 0, ENTRY);
  fs.writeFileSync(f, JSON.stringify(obj, null, 2), "utf8");
  console.log(`${f}: sites ${before} -> ${obj.sites.length}`);
}
