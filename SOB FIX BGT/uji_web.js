// Menjalankan simulator di DOM sungguhan dengan konteks kanvas tiruan, lalu
// memutar beberapa ratus frame. Tujuannya menangkap error runtime -- NaN, properti
// undefined, kanvas yang membengkak -- yang tidak akan pernah terlihat dari
// pemeriksaan sintaks.
const fs = require('fs');
const { JSDOM } = require('jsdom');

const html = fs.readFileSync(process.argv[2], 'utf8');

const calls = [];
function ctxStub() {
  const noop = () => {};
  const c = {
    canvas: null,
    setTransform: noop, clearRect: noop, beginPath: noop, moveTo: noop,
    lineTo: noop, arc: noop, stroke: noop, fill: noop, fillText: noop,
    save: noop, restore: noop, translate: noop, rotate: noop, scale: noop, closePath: noop,
    setLineDash: noop, clip: noop, quadraticCurveTo: noop, bezierCurveTo: noop, ellipse: noop,
    fillRect: noop, strokeRect: noop, measureText: (t) => ({ width: String(t).length * 5.5 }),
    textAlign: 'left', globalAlpha: 1,
    createRadialGradient: (...a) => {
      a.forEach(v => { if (!Number.isFinite(v)) calls.push('gradien NaN: ' + a.join(',')); });
      return { addColorStop: (o, col) => { if (/NaN|undefined/.test(String(col))) calls.push('warna tidak valid: ' + col); } };
    },
    createLinearGradient: () => ({ addColorStop: noop }),
  };
  return new Proxy(c, {
    get(t, k) {
      if (k in t) return t[k];
      return undefined;
    },
    set(t, k, v) {
      if ((k === 'lineWidth' || k === 'font') && (v === undefined || Number.isNaN(v)))
        calls.push('properti ctx tidak valid: ' + String(k));
      t[k] = v; return true;
    },
  });
}

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  beforeParse(w) {
    w.devicePixelRatio = 2;               // uji jalur retina
    w.HTMLCanvasElement.prototype.getContext = function () {
      if (!this.__ctx) { this.__ctx = ctxStub(); this.__ctx.canvas = this; }
      return this.__ctx;
    };
    w.HTMLCanvasElement.prototype.getBoundingClientRect = function () {
      return { width: 640, height: 470, top: 0, left: 0, right: 640, bottom: 470 };
    };
    w.Element.prototype.getBoundingClientRect = w.Element.prototype.getBoundingClientRect
      || function () { return { width: 640, height: 300, top: 0, left: 0 }; };
  },
});

const w = dom.window;
const errors = [];
w.addEventListener('error', e => errors.push('window error: ' + (e.error ? e.error.stack : e.message)));
const origErr = w.console.error;
w.console.error = (...a) => { errors.push('console.error: ' + a.join(' ')); origErr(...a); };

setTimeout(() => {
  const d = w.document;

  // Putar 400 frame.
  let t = 0;
  const raf = w.requestAnimationFrame;
  for (let i = 0; i < 400; i++) {
    t += 16;
    try { w.__frameHook ? w.__frameHook(t) : null; } catch (e) { errors.push('frame: ' + e.message); }
  }

  // jsdom memang menjalankan rAF sendiri; beri waktu lalu periksa.
  setTimeout(() => {
    const checks = [];
    const ok = (n, c, d2 = '') => { checks.push([n, c, d2]); };

    // Kanvas tidak boleh membengkak (bug tinggi berlipat).
    ['lung3d', 'wave', 'scatter'].forEach(id => {
      const c = d.getElementById(id);
      const expect = { lung3d: 470, wave: 180, scatter: 180 }[id];
      ok(`kanvas ${id} stabil`, c.height === expect * 2, `${c.height} (harus ${expect * 2})`);
    });

    // Pembacaan terisi dan bukan NaN.
    ['rMP', 'rGI', 'rDP', 'rPP', 'rCO2', 'rSAT', 'rREC'].forEach(id => {
      const v = d.getElementById(id).textContent;
      ok(`pembacaan ${id}`, v !== '—' && v !== '' && !/NaN/.test(v), v);
    });

    // Interaksi tombol.
    try {
      d.getElementById('btnMark').dispatchEvent(new w.Event('click'));
      ok('tombol tandai', true);
    } catch (e) { ok('tombol tandai', false, e.message); }

    try {
      d.getElementById('btnCollapse').dispatchEvent(new w.Event('click'));
      ok('tombol derekrutmen', true);
    } catch (e) { ok('tombol derekrutmen', false, e.message); }

    try {
      const sc = d.getElementById('scenario');
      sc.value = 'berat';
      sc.dispatchEvent(new w.Event('change'));
      ok('ganti skenario', true);
    } catch (e) { ok('ganti skenario', false, e.message); }

    try {
      const sl = d.getElementById('sCV');
      sl.value = '0.3';
      sl.dispatchEvent(new w.Event('input'));
      ok('slider CV', d.getElementById('vCV').textContent === '0,30',
         d.getElementById('vCV').textContent);
    } catch (e) { ok('slider CV', false, e.message); }

    try {
      const sp = d.getElementById('speed');
      sp.value = '0.9'; sp.dispatchEvent(new w.Event('change'));
      ok('kecepatan simulasi', true);
    } catch (e) { ok('kecepatan simulasi', false, e.message); }

    // Klik pada paru harus memunculkan popover detail lobus.
    try {
      const c = d.getElementById('lung3d');
      let hit = null;
      for (let gx = 180; gx < 520 && !hit; gx += 12)
        for (let gy = 60; gy < 420 && !hit; gy += 12) {
          const ev = new w.MouseEvent('click', { clientX: gx, clientY: gy, bubbles: true });
          c.dispatchEvent(new w.MouseEvent('mousedown', { clientX: gx, clientY: gy }));
          c.dispatchEvent(ev);
          const pop = d.querySelector('.pop');
          if (pop) hit = pop.textContent;
        }
      ok('klik lobus memunculkan detail', !!hit && /Lobus/.test(hit),
         hit ? hit.replace(/\s+/g, ' ').slice(0, 52) : 'tidak ada yang kena');
      const x = d.querySelector('.pop .x');
      if (x) { x.dispatchEvent(new w.Event('click')); }
      ok('popover bisa ditutup', !d.querySelector('.pop'));
    } catch (e) { ok('klik lobus', false, e.message); }

    // Kendali pandangan 3D.
    try {
      const before = { ...w.__CAMSNAP };
      d.querySelector('[data-view="posterior"]').dispatchEvent(new w.Event('click'));
      ok('preset sudut pandang', true);
      ['btnSpin','btnLabels','btnXray'].forEach(id=>{
        const b=d.getElementById(id); const p0=b.getAttribute('aria-pressed');
        b.dispatchEvent(new w.Event('click'));
        if(b.getAttribute('aria-pressed')===p0) throw new Error(id+' tidak berubah');
      });
      ok('tiga tombol alih berfungsi', true);
      d.getElementById('btnXray').dispatchEvent(new w.Event('click'));  // kembalikan
    } catch (e) { ok('kendali pandangan 3D', false, e.message); }

    // Demo terpandu: harus memunculkan indikator tahap.
    try {
      d.getElementById('btnDemo').dispatchEvent(new w.Event('click'));
      const shown = !d.getElementById('stage').hidden;
      const txt = d.getElementById('stageTxt').textContent;
      ok('demo terpandu mulai', shown && /1 dari 4/.test(txt), txt);
      d.getElementById('btnDemo').dispatchEvent(new w.Event('click'));  // hentikan
      ok('demo bisa dihentikan', d.getElementById('stage').hidden);
    } catch (e) { ok('demo terpandu', false, e.message); }

    // Fitur antarmuka baru.
    try {
      const head = d.getElementById('vHead').textContent;
      ok('analisis otomatis terisi', !/Menunggu/.test(head) && head.length > 5, head);
      ok('temuan analisis ditampilkan', d.querySelectorAll('#findings .fnd').length > 0,
         d.querySelectorAll('#findings .fnd').length + ' temuan');
      ok('deskripsi pasien terisi', d.getElementById('scnDesc').textContent.length > 20);
      const pills = [...d.querySelectorAll('.met .pill')].map(x => x.textContent);
      ok('status tiap pembacaan', pills.length === 7 && pills.every(t => /Aman|Waspada|Bahaya/.test(t)), pills.join(','));
      ok('penanda rentang bergerak', [...d.querySelectorAll('.met .mark')].every(m => /%$/.test(m.style.left)));
      d.getElementById('btnGuide').dispatchEvent(new w.Event('click'));
      ok('panduan terbuka', !d.getElementById('guide').hidden);
      d.getElementById('guideX').dispatchEvent(new w.Event('click'));
      ok('panduan tertutup', d.getElementById('guide').hidden);
      const tipBtn = d.querySelector('.tip[data-tip]');
      tipBtn.dispatchEvent(new w.Event('focusin', { bubbles: true }));
      const tb = d.querySelector('.tipbox');
      ok('tooltip muncul', tb && tb.style.display === 'block' && tb.textContent.length > 20);
      ok('cadangan kanvas 2D aktif tanpa WebGL', /2D/.test(d.getElementById('rmode').textContent),
         d.getElementById('rmode').textContent);
    } catch (e) { ok('fitur antarmuka', false, e.message); }

    // MPC. Tombolnya memakai setTimeout, jadi diperiksa di tahap terakhir.
    d.getElementById('btnAuto').dispatchEvent(new w.Event('click'));

    setTimeout(() => {
      const msg = d.getElementById('msg').textContent;
      ok('VIVA-MPC berjalan', /VIVA-MPC memilih/.test(msg), msg.slice(0, 70));
      const cmp = d.getElementById('cmp');
      ok('perbandingan sebelum-sesudah dimulai', !cmp.hidden && /mengukur|hasil/i.test(cmp.textContent),
         cmp.textContent.replace(/\s+/g,' ').slice(0, 40));
      ok('tanpa error runtime', errors.length === 0, errors.slice(0, 3).join(' | '));
      ok('tanpa nilai NaN di kanvas', calls.length === 0, calls.slice(0, 3).join(' | '));

      let fail = 0;
      checks.forEach(([n, c, d2]) => {
        if (!c) fail++;
        console.log(`  [${c ? 'OK ' : 'GAGAL'}] ${n}${d2 ? '  ' + d2 : ''}`);
      });
      console.log(fail === 0 ? '\nSemua pemeriksaan lolos.' : `\n${fail} pemeriksaan gagal.`);
      process.exit(fail === 0 ? 0 : 1);
    }, 2500);
  }, 1200);
}, 600);
