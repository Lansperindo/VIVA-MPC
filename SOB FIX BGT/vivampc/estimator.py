"""
Moving Horizon Estimation untuk mekanika pernapasan.

Model yang dipasang adalah persamaan gerak dengan elastance bergantung volume:

    P_aw(t) = R * Vdot(t) + (E1 + E2 * V(t)) * V(t) + PEEP

Alasan memakai MHE dan bukan recursive least squares biasa:
  * kendala fisik R > 0 dan E1 > 0 bisa dipaksakan secara keras;
  * jendela bergerak memberi pelupaan yang tegas, bukan pelupaan eksponensial
    yang kabur, sehingga perubahan mendadak mekanika terdeteksi lebih cepat;
  * residu dapat diregularisasi ke taksiran sebelumnya (arrival cost), sehingga
    estimasi tidak melompat saat sinyal kurang informatif.

%E2 = E2*V_T / (E1 + E2*V_T) dipakai sebagai indeks overdistensi per napas
(Kano dkk., Bersten, Carvalho dkk.). Nilai positif besar menandakan sistem
mengeras saat volume naik -- tanda overdistensi tidal.
"""

import numpy as np
from scipy.optimize import least_squares


class MechanicsMHE:
    def __init__(self, window_breaths=6, arrival_weight=0.08):
        self.window = window_breaths
        self.arrival_weight = arrival_weight
        self.theta = np.array([10.0, 20.0, 5.0])   # R, E1, E2
        self.buffer = []
        self.history = []

    def push(self, flow, volume, pressure, peep):
        """Simpan satu napas gelombang. Volume DIUKUR RELATIF terhadap akhir
        ekspirasi, seperti pada literatur %E2 klinis; ini yang membuat E1 dan E2
        terpisah dengan baik alih-alih saling menukar nilai."""
        self.buffer.append((np.asarray(flow), np.asarray(volume),
                            np.asarray(pressure), float(peep)))
        if len(self.buffer) > self.window:
            self.buffer.pop(0)

    def solve(self):
        if len(self.buffer) < 2:
            return self._report()

        flow = np.concatenate([b[0] for b in self.buffer])
        vol = np.concatenate([b[1] for b in self.buffer])
        pres = np.concatenate([b[2] for b in self.buffer])
        peep = np.concatenate([np.full(len(b[0]), b[3]) for b in self.buffer])

        # Buang sampel mendekati aliran nol: di sana R tidak teridentifikasi.
        keep = np.abs(flow) > 0.02
        if keep.sum() < 30:
            return self._report()
        flow, vol, pres, peep = flow[keep], vol[keep], pres[keep], peep[keep]

        prior = self.theta.copy()
        scale = np.array([10.0, 20.0, 10.0])

        def residual(theta):
            r, e1, e2 = theta
            model = r * flow + (e1 + e2 * vol) * vol + peep
            fit = (model - pres) / max(pres.std(), 1.0)
            arrival = self.arrival_weight * (theta - prior) / scale
            return np.concatenate([fit, arrival])

        try:
            sol = least_squares(
                residual, prior, method="trf",
                bounds=([1.0, 10.0, -80.0], [90.0, 260.0, 900.0]),
                max_nfev=220, xtol=1e-9,
            )
            self.theta = sol.x
        except Exception:
            pass

        self.history.append(self.theta.copy())
        return self._report()

    def _report(self):
        r, e1, e2 = self.theta
        return {"R": float(r), "E1": float(e1), "E2": float(e2),
                "C_static": float(1000.0 / max(e1, 1e-6))}

    def percent_e2(self, vt):
        """Indeks overdistensi, dalam persen, pada tidal volume yang diberikan."""
        _, e1, e2 = self.theta
        denom = e1 + e2 * vt
        return float(100.0 * e2 * vt / denom) if abs(denom) > 1e-9 else 0.0
