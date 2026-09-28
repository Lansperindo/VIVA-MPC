"""
Tiga pembanding. Tanpa pembanding yang jujur, angka VIVA-MPC tidak berarti apa-apa.

  ARDSNet   protokol tabel PEEP/FiO2, VT 6 mL/kg PBW, tanpa variabilitas.
  ASV-like  frekuensi optimal Otis yang meminimalkan kerja napas -- inilah prinsip
            yang dipakai Adaptive Support Ventilation (Tehrani, US 4,986,268).
  NoisyPCV  setara praktik ventilasi variabel di literatur: CV dipatok 30%,
            distribusi simetris, tanpa struktur korelasi temporal. Inilah
            pembanding yang paling penting, karena ia memakai variabilitas
            tetapi tidak mengoptimasinya.
"""

import numpy as np

# Tabel PEEP/FiO2 lengan lower-PEEP ARDSNet.
_FIO2_GRID = [0.30, 0.40, 0.40, 0.50, 0.50, 0.60, 0.70, 0.70, 0.70, 0.80, 0.90, 0.90, 0.90, 1.00]
_PEEP_GRID = [5.0, 5.0, 8.0, 8.0, 10.0, 10.0, 10.0, 12.0, 14.0, 14.0, 14.0, 16.0, 18.0, 20.0]


def predicted_body_weight(height_cm=170.0, male=True):
    base = 50.0 if male else 45.5
    return base + 0.91 * (height_cm - 152.4)


class BaselineController:
    """Antarmuka yang sama dengan VivaMPC.step supaya perbandingan adil."""

    name = "baseline"

    def __init__(self, weight_kg=70.0):
        self.weight = weight_kg
        self.u = np.array([0.42, 8.0, 18.0, 0.50, 0.0, 0.0, 0.0])
        self.trace = []

    def step(self, state, mechanics=None):
        raise NotImplementedError


class ARDSNet(BaselineController):
    name = "ARDSNet"

    def __init__(self, weight_kg=70.0, ml_per_kg=6.0):
        super().__init__(weight_kg)
        self.vt = ml_per_kg * weight_kg / 1000.0

    def step(self, state, mechanics=None):
        fio2, peep = self._titrate(state.get("spo2", 95.0), self.u[3], self.u[1])
        rr = self.u[2]
        paco2 = state.get("paco2", 40.0)
        if paco2 > 48.0:
            rr = min(32.0, rr + 2.0)
        elif paco2 < 34.0:
            rr = max(12.0, rr - 2.0)
        self.u = np.array([self.vt, peep, rr, fio2, 0.0, 0.0, 0.0])
        self.trace.append({"u_safe": self.u.copy(), "clipped": False, "cost": None})
        return self.u

    @staticmethod
    def _titrate(spo2, fio2, peep):
        idx = int(np.argmin([abs(f - fio2) for f in _FIO2_GRID]))
        if spo2 < 90.0:
            idx = min(idx + 1, len(_FIO2_GRID) - 1)
        elif spo2 > 97.0:
            idx = max(idx - 1, 0)
        return _FIO2_GRID[idx], _PEEP_GRID[idx]


class ASVLike(BaselineController):
    """Frekuensi optimal Otis: meminimalkan kerja napas pada ventilasi semenit tetap."""

    name = "ASV-like"

    def __init__(self, weight_kg=70.0, minute_target=None):
        super().__init__(weight_kg)
        self.mv = minute_target or 0.1 * weight_kg   # L/menit, 100 mL/kg
        self.vd = 2.2e-3 * weight_kg + 0.055

    def step(self, state, mechanics=None):
        rc = 0.6
        if mechanics:
            rc = np.clip(mechanics["R"] * mechanics["C_static"] / 1000.0, 0.15, 1.8)

        # f_opt = (-1 + sqrt(1 + 4 pi^2 RC MV / VD)) / (2 pi^2 RC), Otis dkk. 1950
        inner = 1.0 + 4.0 * np.pi ** 2 * rc * (self.mv / 60.0) / self.vd
        f_opt = (-1.0 + np.sqrt(inner)) / (2.0 * np.pi ** 2 * rc) * 60.0
        rr = float(np.clip(f_opt, 12.0, 32.0))
        vt = float(np.clip(self.mv / rr, 0.25, 0.60))

        fio2, peep = ARDSNet._titrate(state.get("spo2", 95.0), self.u[3], self.u[1])
        self.u = np.array([vt, peep, rr, fio2, 0.0, 0.0, 0.0])
        self.trace.append({"u_safe": self.u.copy(), "clipped": False, "cost": None})
        return self.u


class NoisyPCV(ARDSNet):
    """Ventilasi variabel gaya literatur: CV dipatok, bentuk dan korelasi dibekukan."""

    name = "Noisy PCV (CV 30%)"

    def __init__(self, weight_kg=70.0, cv=0.30):
        super().__init__(weight_kg)
        self.cv = cv

    def step(self, state, mechanics=None):
        u = super().step(state, mechanics)
        u[4] = self.cv
        self.u = u
        self.trace[-1]["u_safe"] = u.copy()
        return u
