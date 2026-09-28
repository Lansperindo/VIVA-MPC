"""
Jalankan ini lebih dulu. Selesai dalam beberapa detik dan memastikan
semuanya terpasang benar sebelum Anda menunggu eksperimen yang panjang.
"""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import numpy as np

from vivampc import (BreathSurrogate, LungPlant, MechanicsMHE,
                     PressureVentilator, VivaMPC, breath_pattern,
                     realised_moments, spectral_exponent)

np.seterr(all="ignore")
ok = True


def cek(nama, syarat, detail=""):
    global ok
    ok = ok and syarat
    print(f"  [{'OK ' if syarat else 'GAGAL'}] {nama}{'  ' + detail if detail else ''}")


print("1. Generator pola napas")
vt, tt = breath_pattern(512, 0.42, 18, cv=0.30, gamma=0.5, beta=1.0,
                        rng=np.random.default_rng(0))
m = realised_moments(vt)
b = spectral_exponent(vt)
cek("CV terwujud", abs(m["cv"] - 0.30) < 0.02, f"{m['cv']:.3f}")
cek("kemencengan terwujud", abs(m["skewness"] - 0.5) < 0.2, f"{m['skewness']:+.2f}")
cek("eksponen fraktal", abs(b - 1.0) < 0.35, f"{b:.2f}")
mv = vt / tt * 60.0
cek("ventilasi semenit konstan", float(mv.max() - mv.min()) < 1e-9)

print("\n2. Digital twin")
p = LungPlant(c_total=32, r_airway=10, p_open_mean=20, p_open_sd=9, seed=0)
p.reset(peep=10)
v = PressureVentilator(p, peep=10, fio2=0.5)
mhe = MechanicsMHE()
for _ in range(120):
    r, w = v.deliver(0.40, 3.33, collect_waveform=True)
    w = np.array(w)
    mhe.push(w[:, 2], w[:, 3], w[:, 1], 10)
e = mhe.solve()
cek("tidal volume terlacak", abs(r.vt - 0.40) < 0.01, f"{r.vt:.3f} L")
cek("tekanan masuk akal", 15 < r.peak < 60, f"Ppeak {r.peak:.1f}")
cek("estimator menemukan R", 5 < e["R"] < 25, f"R {e['R']:.1f} (sebenarnya 10)")
cek("gas exchange waras", 25 < p.paco2 < 90, f"PaCO2 {p.paco2:.0f}")

print("\n3. Controller")
import time
mpc = VivaMPC(BreathSurrogate(c_total=32, r_airway=10), weight_kg=70, seed=0)
st = {"s": np.full(20, 0.45), "paco2": 50.0, "pao2": 80.0, "spo2": 94.0}
t0 = time.time()
u = mpc.step(st, e)
dt = time.time() - t0
cek("MPC menghasilkan solusi", np.all(np.isfinite(u)))
cek("waktu solve wajar", dt < 6.0, f"{dt * 1000:.0f} ms")
print(f"       VT={u[0]:.3f} PEEP={u[1]:.1f} RR={u[2]:.1f} FiO2={u[3]:.2f} "
      f"CV={u[4]:.3f} gamma={u[5]:+.2f} beta={u[6]:.2f}")

print("\n" + ("Semua beres. Lanjut ke run_pareto.py atau run_experiments.py."
               if ok else "Ada yang gagal di atas. Periksa versi numpy dan scipy."))
sys.exit(0 if ok else 1)
