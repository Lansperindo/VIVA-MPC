"""
Sapuan Pareto dan ablasi.

Pertanyaan yang dijawab skrip ini adalah pertanyaan yang benar, dan berbeda dari
"apakah VIVA-MPC lebih baik". Membandingkan dua controller lewat satu angka skalar
selalu bisa dipatahkan penguji: angka itu bergantung pada bobot yang kita pilih
sendiri. Yang tidak bisa dipatahkan adalah frontier.

Untuk setiap bobot GI, controller yang sama dijalankan dalam empat varian:

    CV dipatok 0      -- MPC biasa, tanpa variabilitas sama sekali
    CV dipatok 0.15   -- ventilasi variabel dosis sedang
    CV dipatok 0.30   -- dosis baku literatur (Gama de Abreu, Kiss dkk.)
    CV bebas          -- VIVA-MPC penuh, variabilitas ikut dioptimasi

Ketiga varian pertama berbagi seluruh mesin yang sama: twin, estimator, surrogate,
CEM, safety supervisor. Satu-satunya yang berbeda adalah apakah parameter bentuk
ikut menjadi variabel keputusan. Selisih yang muncul karena itu saja adalah
sumbangan bersih dari klaim kebaruan.
"""

import json
import sys
import time
import warnings

import numpy as np

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")
np.seterr(all="ignore")

from vivampc import BreathSurrogate, VivaMPC, simulate, summarise
from vivampc.scenarios import SCENARIOS

WEIGHT = 70.0
MINUTES = 10.0
SEED = 1
GI_WEIGHTS = [2.0, 10.0, 30.0, 80.0]
VARIANTS = {
    "CV=0": (0.0, 0.0, 0.0),
    "CV=0.15": (0.15, 0.0, 0.0),
    "CV=0.30": (0.30, 0.0, 0.0),
    "CV bebas": None,
}
SCENARIO = "ards_sedang"

plant_kw = SCENARIOS[SCENARIO]["plant"]
rows = []
t0 = time.time()

for wgi in GI_WEIGHTS:
    for vname, fixv in VARIANTS.items():
        sur = BreathSurrogate(c_total=plant_kw["c_total"], r_airway=plant_kw["r_airway"])
        weights = {"mp": 1.00, "gi": wgi, "paco2": 0.075, "spo2": 0.55,
                   "move": 0.60, "barrier": 45.0}
        ctrl = VivaMPC(sur, weights=weights, weight_kg=WEIGHT, seed=SEED,
                       fix_variability=fixv)
        res = simulate(ctrl, plant_kwargs=plant_kw, minutes=MINUTES,
                       seed=SEED, weight_kg=WEIGHT)
        s = summarise(res)
        s["w_gi"] = wgi
        s["variant"] = vname
        u = res["control"][-1]["u"]
        s["cv_final"] = float(u[4])
        s["gamma_final"] = float(u[5])
        s["beta_final"] = float(u[6])
        rows.append(s)
        print(f"w_gi={wgi:5.1f}  {vname:<9s}  MP={s['mp_mean']:5.1f}  "
              f"GI={s['gi_mean']:.3f}  dP={s['driving_mean']:5.1f}  "
              f"PaCO2={s['paco2_mean']:5.1f}  SpO2={s['spo2_mean']:5.1f}  "
              f"CVreal={s['vt_cv_realised']:.3f}", flush=True)

print(f"\nsapuan selesai dalam {time.time() - t0:.0f} s")
with open(str(ROOT / "pareto.json"), "w") as f:
    json.dump({"rows": rows, "scenario": SCENARIO, "minutes": MINUTES}, f)
print("tersimpan")
