// Merender mesh paru memakai kode pencahayaan yang sama persis dengan halaman,
// lalu menulisnya sebagai PNG. Tanpa ini saya cuma menebak warnanya.
const fs = require('fs');
const zlib = require('zlib');

const html = fs.readFileSync(process.argv[2], 'utf8');
const js = html.match(/<script>([\s\S]*)<\/script>/)[1];
const blk = js.match(/const CAM=\{[\s\S]*?(?=const VIEW=)/)[0];
fs.writeFileSync('/tmp/webtest/r.js',
  'const N=20;' + blk + '\nmodule.exports={LUNGS,project,rot,surfaceNormals,LIGHT,CAM,NU,NV:NVT,tissue,BRONCHI,CENTERS};');
const M = require('/tmp/webtest/r.js');

if (process.argv[4]) M.CAM.yaw = parseFloat(process.argv[4]);

const W = 760, H = 470;
const img = new Uint8Array(W * H * 3);
const zb = new Float64Array(W * H).fill(1e9);

// latar: gradien radial seperti CSS halaman
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
  const dx = (x - W * 0.5) / (W * 0.6), dy = (y - H * 0.18) / (H * 0.9);
  const t = Math.min(1, Math.hypot(dx, dy));
  const c = [253 + (230 - 253) * t, 252 + (224 - 252) * t, 250 + (214 - 250) * t];
  const i = (y * W + x) * 3;
  img[i] = c[0]; img[i + 1] = c[1]; img[i + 2] = c[2];
}

function tri(p, col, depth) {
  const x0 = Math.max(0, Math.floor(Math.min(...p.map(q => q.x))));
  const x1 = Math.min(W - 1, Math.ceil(Math.max(...p.map(q => q.x))));
  const y0 = Math.max(0, Math.floor(Math.min(...p.map(q => q.y))));
  const y1 = Math.min(H - 1, Math.ceil(Math.max(...p.map(q => q.y))));
  const px = p.map(q => q.x), py = p.map(q => q.y), n = p.length;
  for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
    let inside = false;
    for (let a = 0, b = n - 1; a < n; b = a++)
      if ((py[a] > y + 0.5) !== (py[b] > y + 0.5) &&
          x + 0.5 < (px[b] - px[a]) * (y + 0.5 - py[a]) / (py[b] - py[a]) + px[a]) inside = !inside;
    if (!inside) continue;
    const k = y * W + x;
    if (depth >= zb[k]) continue;
    zb[k] = depth;
    const i = k * 3;
    img[i] = col[0]; img[i + 1] = col[1]; img[i + 2] = col[2];
  }
}

const XRAY = process.argv[3] === 'xray';
const S = new Array(20).fill(process.argv[6]?parseFloat(process.argv[6]):0.85);

// bayangan kontak
const gy = M.project([0, -1.24, 0], W, H), gr = 0.95 * gy.k;
for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
  const d = Math.hypot((x - gy.x) / gr, (y - gy.y - 8) / (gr * 0.26));
  if (d < 1) {
    const a = 0.15 * (1 - d) ** 1.6, i = (y * W + x) * 3;
    for (let c = 0; c < 3; c++) img[i + c] = img[i + c] * (1 - a) + 22 * a;
  }
}

// trakea
(function () {
  const a = M.project([0, 1.44, 0], W, H), b = M.project([0, 0.86, 0], W, H);
  const w = Math.max(4, 0.050 * a.k);
  for (let t = 0; t <= 1; t += 0.002) {
    const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
    for (let dy = -w; dy <= w; dy++) for (let dx = -w; dx <= w; dx++) {
      if (dx * dx + dy * dy > w * w) continue;
      const px = Math.round(x + dx), py = Math.round(y + dy);
      if (px < 0 || py < 0 || px >= W || py >= H) continue;
      const k = py * W + px; if (a.d >= zb[k]) continue; zb[k] = a.d;
      const i = k * 3; img[i] = 188; img[i + 1] = 174; img[i + 2] = 156;
    }
  }
})();

const quads = [];
let FACE = 1;
M.LUNGS.forEach(L => {
  const nrm = M.surfaceNormals(L.verts);
  const pr = L.verts.map(v => M.project(v, W, H));
  const nr = nrm.map(M.rot);
  { let best = 0;
    for (let iv=0; iv<M.NV; iv++) for (let iu=0; iu<M.NU; iu++) {
      const a=iv*M.NU+iu,b=iv*M.NU+(iu+1)%M.NU,c=(iv+1)*M.NU+(iu+1)%M.NU,d2=(iv+1)*M.NU+iu;
      const nz=(nr[a][2]+nr[b][2]+nr[c][2]+nr[d2][2])/4; if(nz>-0.6) continue;
      const ar=(pr[b].x-pr[a].x)*(pr[c].y-pr[a].y)-(pr[c].x-pr[a].x)*(pr[b].y-pr[a].y);
      if(Math.abs(ar)>Math.abs(best)) best=ar; }
    FACE = best!==0 ? Math.sign(best) : 1; }
  for (let iv = 0; iv < M.NV; iv++) for (let iu = 0; iu < M.NU; iu++) {
    const i0 = iv * M.NU + iu, i1 = iv * M.NU + (iu + 1) % M.NU;
    const i2 = (iv + 1) * M.NU + (iu + 1) % M.NU, i3 = (iv + 1) * M.NU + iu;
    const A=pr[i0],B=pr[i1],C=pr[i2],D=pr[i3];
    const area=(B.x-A.x)*(C.y-A.y)-(C.x-A.x)*(B.y-A.y)
              +(C.x-A.x)*(D.y-A.y)-(D.x-A.x)*(C.y-A.y);
    if (area*FACE <= 0) continue;
    const nz = (nr[i0][2] + nr[i1][2] + nr[i2][2] + nr[i3][2]) / 4;
    const nx = (nr[i0][0] + nr[i1][0] + nr[i2][0] + nr[i3][0]) / 4;
    const ny = (nr[i0][1] + nr[i1][1] + nr[i2][1] + nr[i3][1]) / 4;
    const m = Math.hypot(nx, ny, nz) || 1;
    let sAvg = 0, tot = 0;
    [i0, i1, i2, i3].forEach(k => { const wt = L.wts[k];
      for (let z = 0; z < wt.length; z++) { sAvg += wt[z][1] * S[wt[z][0]]; tot += wt[z][1]; } });
    quads.push({ p: [pr[i0], pr[i1], pr[i2], pr[i3]], n: [nx / m, ny / m, nz / m],
      s: sAvg / (tot || 1), d: (pr[i0].d + pr[i1].d + pr[i2].d + pr[i3].d) / 4 });
  }
});
quads.sort((a, b) => b.d - a.d);

const L = M.LIGHT;
quads.forEach(q => {
  const ndl = Math.max(0, q.n[0] * L[0] + q.n[1] * L[1] + q.n[2] * L[2]);
  const wrap = Math.max(0, (q.n[1] * 0.5 + 0.5)) * 0.12;
  const lit = Math.min(1, 0.42 + 0.52 * ndl + wrap);
  const rim = Math.pow(1 - Math.min(1, Math.abs(q.n[2])), 3) * 0.26;
  const hx = L[0], hy = L[1], hz = L[2] - 1, hm = Math.hypot(hx, hy, hz) || 1;
  const ndh = Math.max(0, (q.n[0] * hx + q.n[1] * hy + q.n[2] * hz) / hm);
  const spec = Math.pow(ndh, 26) * 0.42;
  const c = M.tissue(q.s);
  q.lobe=[0,0]; const col = c.map(v => { const b = v * lit; const r = b + (255 - b) * rim * 0.50;
    return Math.round(Math.min(255, r + (255 - r) * spec)); });
  tri(q.p, col, q.d);
});

// garis fisura, supaya pembagian lobus bisa dinilai
M.LUNGS.forEach(L => {
  const pr = L.verts.map(v => M.project(v, W, H));
  for (let iv = 0; iv < M.NV; iv++) for (let iu = 0; iu < M.NU; iu++) {
    const i0 = iv * M.NU + iu, i1 = iv * M.NU + (iu + 1) % M.NU, i3 = (iv + 1) * M.NU + iu;
    const seg = [];
    if (L.lobes[i0] !== L.lobes[i3]) seg.push([pr[i0], pr[i1]]);
    if (L.lobes[i0] !== L.lobes[i1]) seg.push([pr[i0], pr[i3]]);
    seg.forEach(([a, b]) => {
      const n = Math.ceil(Math.hypot(b.x - a.x, b.y - a.y)) + 1;
      for (let t = 0; t <= n; t++) {
        const x = Math.round(a.x + (b.x - a.x) * t / n), y = Math.round(a.y + (b.y - a.y) * t / n);
        if (x < 0 || y < 0 || x >= W || y >= H) continue;
        const k = y * W + x; if (a.d > zb[k] + 0.08) continue;
        const i = k * 3;
        for (let c = 0; c < 3; c++) img[i + c] = img[i + c] * 0.72 + [74, 40, 38][c] * 0.28;
      }
    });
  }
});

// --- tulis PNG ---
const raw = Buffer.alloc((W * 3 + 1) * H);
for (let y = 0; y < H; y++) {
  raw[y * (W * 3 + 1)] = 0;
  Buffer.from(img.buffer, y * W * 3, W * 3).copy(raw, y * (W * 3 + 1) + 1);
}
function chunk(type, data) {
  const len = Buffer.alloc(4); len.writeUInt32BE(data.length);
  const td = Buffer.concat([Buffer.from(type), data]);
  const crc = Buffer.alloc(4); crc.writeUInt32BE(crc32(td) >>> 0);
  return Buffer.concat([len, td, crc]);
}
let TBL = null;
function crc32(buf) {
  if (!TBL) { TBL = new Int32Array(256);
    for (let n = 0; n < 256; n++) { let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; TBL[n] = c; } }
  let c = -1; for (const b of buf) c = TBL[(c ^ b) & 0xFF] ^ (c >>> 8); return c ^ -1;
}
const ihdr = Buffer.alloc(13);
ihdr.writeUInt32BE(W, 0); ihdr.writeUInt32BE(H, 4);
ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
fs.writeFileSync(process.argv[5] || '/tmp/webtest/lung.png', Buffer.concat([
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
  chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0)),
]));
console.log('render: ' + quads.length + ' quad');
