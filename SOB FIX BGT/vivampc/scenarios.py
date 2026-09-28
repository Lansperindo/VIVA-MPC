"""
Matriks skenario. Parameter dipilih agar rentang compliance dan resistansi
mencakup sembilan konfigurasi test lung yang disyaratkan ISO 80601-2-80, sehingga
hasil in-silico bisa langsung dipetakan ke pengujian hardware-in-the-loop nanti.
"""

import numpy as np

SCENARIOS = {
    "sehat": dict(
        label="Paru sehat",
        plant=dict(c_total=55.0, r_airway=5.0, p_open_mean=8.0, p_open_sd=3.0,
                   e2_frac=0.15, shunt_floor=0.03),
    ),
    "ards_ringan": dict(
        label="ARDS ringan",
        plant=dict(c_total=42.0, r_airway=8.0, p_open_mean=15.0, p_open_sd=7.0,
                   e2_frac=0.22, shunt_floor=0.06),
    ),
    "ards_sedang": dict(
        label="ARDS sedang",
        plant=dict(c_total=32.0, r_airway=10.0, p_open_mean=20.0, p_open_sd=9.0,
                   e2_frac=0.26, shunt_floor=0.09),
    ),
    "ards_berat": dict(
        label="ARDS berat",
        plant=dict(c_total=23.0, r_airway=11.0, p_open_mean=26.0, p_open_sd=11.0,
                   e2_frac=0.32, shunt_floor=0.13),
    ),
    "obstruktif": dict(
        label="Obstruktif",
        plant=dict(c_total=50.0, r_airway=24.0, p_open_mean=8.0, p_open_sd=3.0,
                   e2_frac=0.15, shunt_floor=0.04),
    ),
    "derekrutmen": dict(
        label="Derekrutmen mendadak",
        plant=dict(c_total=40.0, r_airway=9.0, p_open_mean=16.0, p_open_sd=8.0,
                   e2_frac=0.24, shunt_floor=0.06),
        disturbance="collapse",
    ),
}


def make_disturbance(kind, onset_s=300.0):
    """
    Gangguan dinamis. Inilah ujian yang paling membedakan: setting statis yang
    bagus di awal belum tentu bagus setelah paru berubah.
    """
    if kind is None:
        return None

    if kind == "collapse":
        fired = {"done": False}

        def collapse(plant, t):
            # Kolaps mendadak pada menit ke-5: separuh unit tertutup dan ambang
            # pembukaannya naik, meniru hilangnya surfaktan atau aspirasi.
            if t >= onset_s and not fired["done"]:
                fired["done"] = True
                half = plant.n // 2
                idx = np.argsort(plant.p_open)[half:]
                plant.s[idx] = 0.02
                plant.p_open[idx] *= 1.45
                plant.p_close[idx] = 0.32 * plant.p_open[idx]
                plant.shunt_floor = min(0.30, plant.shunt_floor + 0.12)

        return collapse

    raise ValueError(f"gangguan tidak dikenal: {kind}")
