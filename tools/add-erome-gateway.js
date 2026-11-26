// 把 erome-lan（type 1，走本机 8082 网关）插到 sexkbj-lan 之后，两个配置一起改。
const fs = require("fs");
const path = require("path");

const REPO = "C:/Users/plsharevme/tvbox-repo";
const IP = process.argv[2] || "10.20.116.223";

const ENTRY = {
  key: "erome-lan",
  name: "EroMe[网关]",
  type: 1,
  api: `http://${IP}:8082/api.php/provide/vod/`,
  searchable: 1,
  quickSearch: 1,
};

for (const file of ["tv18.json", "tv18-standalone.json"]) {
  const p = path.join(REPO, file);
  const text = fs.readFileSync(p, "utf8");
  const obj = JSON.parse(text);
  const before = obj.sites.length;
  obj.sites = obj.sites.filter((s) => s.key !== ENTRY.key);
  const idx = obj.sites.findIndex((s) => s.key === "sexkbj-lan");
  const at = idx >= 0 ? idx + 1 : 1;
  obj.sites.splice(at, 0, ENTRY);
  const out = JSON.stringify(obj, null, 2) + "\n";
  fs.writeFileSync(p, out, "utf8");
  console.log(`${file}: ${before} -> ${obj.sites.length} sites, erome-lan at index ${at}`);
}

console.log("first3:", ["tv18.json"].map((f) => {
  const o = JSON.parse(fs.readFileSync(path.join(REPO, f), "utf8"));
  return o.sites.slice(0, 4).map((s) => s.key).join(" | ");
})[0]);
