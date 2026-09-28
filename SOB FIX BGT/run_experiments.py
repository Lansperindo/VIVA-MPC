"""Jalankan matriks eksperimen penuh dan simpan hasilnya."""

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

from vivampc import (ARDSNet, ASVLike, BreathSurrogate, NoisyPCV, VivaMPC,
                     simulate, summarise)
from vivampc.scenarios import SCENARIOS, make_disturbance

WEIGHT = 70.0
MINUTES = 9.0
SEEDS = [1, 2]


def build(name, plant_kw, seed):
    if name == "ARDSNet":
        return ARDSNet(WEIGHT)
    if name == "ASV-like":
        return ASVLike(WEIGHT)
    if name == "Noisy PCV (CV 30%)":
        return NoisyPCV(WEIGHT, cv=0.30)
    sur = BreathSurrogate(c_total=plant_kw["c_total"], r_airway=plant_kw["r_airway"])
    return VivaMPC(sur, weight_kg=WEIGHT, seed=seed)


CONTROLLERS = ["ARDSNet", "ASV-like", "Noisy PCV (CV 30%)", "VIVA-MPC"]

rows, traces = [], {}
t_start = time.time()

for key, spec in SCENARIOS.items():
    dist = make_disturbance(spec.get("disturbance"))
    for cname in CONTROLLERS:
        per_seed = []
        for seed in SEEDS:
            ctrl = build(cname, spec["plant"], seed)
            res = simulate(ctrl, plant_kwargs=spec["plant"], minutes=MINUTES,
                           seed=seed, disturbance=dist, weight_kg=WEIGHT)
            s = summarise(res)
            s["escalations"] = sum(1 for tr in getattr(ctrl, "trace", [])
                                   if tr.get("escalated"))
            per_seed.append(s)
            if seed == SEEDS[0]:
                traces[f"{key}|{cname}"] = {
                    "breaths": res["breaths"],
                    "control": [{"t": c["t"], "u": c["u"].tolist(),
                                 "mech": c["mech"], "pct_e2": c["pct_e2"]}
                                for c in res["control"]],
                }

        agg = {"scenario": key, "label": spec["label"], "controller": cname}
        for k in per_seed[0]:
            if isinstance(per_seed[0][k], (int, float)):
                vals = [p[k] for p in per_seed]
                agg[k] = float(np.mean(vals))
                agg[k + "_sd"] = float(np.std(vals))
        rows.append(agg)
        print(f"{spec['label']:<24s} {cname:<20s} "
              f"MP={agg['mp_mean']:5.1f}  GI={agg['gi_mean']:.3f}  "
              f"dP={agg['driving_mean']:5.1f}  PaCO2={agg['paco2_mean']:5.1f}  "
              f"SpO2={agg['spo2_mean']:5.1f}  rec={agg['recruited_final']:.2f}  "
              f"CV={agg['vt_cv_realised']:.3f}", flush=True)

print(f"\nselesai dalam {time.time() - t_start:.0f} s")

with open(str(ROOT / "results.json"), "w") as f:
    json.dump({"rows": rows, "minutes": MINUTES, "seeds": SEEDS}, f)

np.save(str(ROOT / "traces.npy"), traces, allow_pickle=True)
print("hasil tersimpan")
