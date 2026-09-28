"""
Loop closed-loop: merangkai lapis 0 sampai 4 menjadi satu simulasi berjalan.

Struktur waktu dua kecepatan, dan ini disengaja:
  * loop cepat  -- setiap napas: LMS menyesuaikan driving pressure, MHE menyerap
                   gelombang baru, metrik dihitung.
  * loop lambat -- setiap `control_interval` napas: MPC menyelesaikan optimisasi
                   dan menetapkan setting baru termasuk parameter variabilitas.

Pemisahan ini juga jawaban praktis untuk keterbatasan EIT: rekonstruksi citra EIT
tidak cukup cepat untuk loop per napas, tetapi lebih dari cukup untuk loop lambat.
"""

import numpy as np

from .estimator import MechanicsMHE
from .plant import LungPlant
from .variability import breath_pattern
from .ventilator import DT, PressureVentilator


def simulate(controller, plant_kwargs=None, minutes=20.0, control_interval=20,
             seed=1, disturbance=None, weight_kg=70.0):
    """
    disturbance: fungsi (plant, t_detik) -> None, dipanggil tiap napas.
                 Dipakai untuk menyuntikkan derekrutmen mendadak atau pemulihan.
    """
    plant = LungPlant(**(plant_kwargs or {}), seed=seed)
    rng = np.random.default_rng(seed + 977)

    init = plant.state_snapshot()
    init["s"] = plant.s.copy()
    u = controller.step(init)
    plant.reset(peep=u[1])
    vent = PressureVentilator(plant, peep=u[1], fio2=u[3])
    mhe = MechanicsMHE(window_breaths=6)

    t = 0.0
    breaths, control_events = [], []
    pattern, times, ptr = None, None, 0

    while t < minutes * 60.0:
        if pattern is None or ptr >= len(pattern):
            vt_m, peep, rr, fio2, cv, gamma, beta = u
            pattern, times = breath_pattern(control_interval, vt_m, rr, cv, gamma, beta, rng)
            ptr = 0
            vent.set_peep(peep)
            vent.fio2 = fio2

        if disturbance is not None:
            disturbance(plant, t)

        rec, wave = vent.deliver(pattern[ptr], times[ptr], collect_waveform=True)
        wave = np.array(wave)
        # wave kolom: t, p_aw, flow, volume
        mhe.push(wave[:, 2], wave[:, 3], wave[:, 1], vent.peep)

        d = rec.as_dict()
        d.update({"t": t, "cv_set": u[4], "gamma_set": u[5], "beta_set": u[6],
                  "vt_set": u[0], "rr_set": u[2], "fio2_set": u[3]})
        breaths.append(d)

        t += rec.t_tot
        ptr += 1

        if ptr >= len(pattern):
            mech = mhe.solve()
            state = {"s": plant.s.copy(), "paco2": plant.paco2,
                     "pao2": plant.pao2, "spo2": plant.spo2}
            u = controller.step(state, mech)
            control_events.append({
                "t": t, "u": np.asarray(u).copy(), "mech": dict(mech),
                "pct_e2": mhe.percent_e2(u[0]),
            })

    return {"breaths": breaths, "control": control_events,
            "plant": plant, "mhe": mhe, "name": getattr(controller, "name", "VIVA-MPC")}


def summarise(result, warmup_fraction=0.25):
    """Ringkas hasil. Periode pemanasan dibuang supaya transien awal tidak mendominasi."""
    b = result["breaths"]
    start = int(len(b) * warmup_fraction)
    seg = b[start:]
    if not seg:
        return {}

    arr = lambda k: np.array([x[k] for x in seg])
    total_time = sum(x["t_tot"] for x in seg) / 60.0

    mp = arr("mp")
    plateau, driving = arr("plateau"), arr("driving")
    return {
        "controller": result["name"],
        "n_breaths": len(seg),
        "mp_mean": float(mp.mean()),
        "mp_cumulative_J": float(np.sum(mp * np.array([x["t_tot"] for x in seg]) / 60.0)),
        "gi_mean": float(arr("gi").mean()),
        "driving_mean": float(driving.mean()),
        "plateau_p95": float(np.percentile(plateau, 95)),
        "vt_cv_realised": float(arr("vt").std() / arr("vt").mean()),
        "paco2_mean": float(arr("paco2").mean()),
        "spo2_mean": float(arr("spo2").mean()),
        "recruited_final": float(arr("recruited")[-1]),
        "pct_breaths_plateau_over_30": float(100.0 * np.mean(plateau > 30.0)),
        "pct_breaths_driving_over_15": float(100.0 * np.mean(driving > 15.0)),
        "pct_breaths_mp_over_17": float(100.0 * np.mean(mp > 17.0)),
        "escalations": 0,
        "minutes": float(total_time),
    }
