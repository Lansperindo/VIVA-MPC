"""
Ventilator pressure-controlled dengan loop dalam LMS adaptif.

Loop dalam ini sengaja dibuat setara dengan controller Beda dkk. (Intensive Care
Med 2010): ia menyesuaikan driving pressure napas demi napas agar tidal volume yang
terwujud mengikuti barisan target. Dengan menempatkannya sebagai KOMPONEN, batas
kebaruan VIVA-MPC menjadi jelas dan bisa dipertahankan di depan penguji:

    Beda 2010   -> merealisasikan pola variabilitas yang sudah ditetapkan operator
    VIVA-MPC    -> memilih pola variabilitas itu sendiri, napas demi napas

Metrik per napas dihitung di sini karena semuanya butuh gelombang intra-napas:
mechanical power butuh tekanan puncak dan plateau, GI index butuh distribusi
volume tidal antar kompartemen.
"""

import numpy as np

DT = 0.004  # 4 ms; cukup halus untuk rise time 0.15 s


class BreathRecord:
    __slots__ = ("vt", "vt_target", "peak", "plateau", "peep", "driving", "mp",
                 "gi", "flow_peak", "t_tot", "paco2", "spo2", "recruited",
                 "shunt", "regional")

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)

    def as_dict(self):
        return {s: getattr(self, s) for s in self.__slots__ if s != "regional"}


class PressureVentilator:
    def __init__(self, plant, peep=8.0, fio2=0.5, ie_ratio=0.5, rise_time=0.15,
                 lms_gain=0.35, driving_init=12.0):
        self.plant = plant
        self.peep = peep
        self.fio2 = fio2
        self.ie = ie_ratio
        self.rise = rise_time
        self.mu = lms_gain
        self.driving = driving_init
        self._c_est = 0.035  # L/cmH2O, ditarik ke nilai nyata oleh LMS

    def set_peep(self, peep):
        self.peep = float(peep)

    def deliver(self, vt_target, t_tot, collect_waveform=False):
        """Berikan satu napas. Mengembalikan BreathRecord (dan gelombang bila diminta)."""
        t_insp = t_tot * self.ie / (1.0 + self.ie)
        n_i = max(2, int(t_insp / DT))
        n_e = max(2, int((t_tot - t_insp) / DT))

        p_set = self.peep + self.driving
        v_start = self.plant.v.copy()
        v0 = float(v_start.sum())
        peak_p, peak_flow = -1e9, 0.0
        wave = [] if collect_waveform else None

        for k in range(n_i):
            ramp = min(1.0, (k * DT) / self.rise) if self.rise > 0 else 1.0
            target = self.peep + self.driving * ramp
            q, _ = self.plant.step(target, DT)
            # Tekanan yang direkam adalah tekanan di Y-piece, yaitu apa yang
            # benar-benar diukur ventilator. Ini penting: kalau yang dipakai
            # tekanan di balik resistansi jalan napas, suku R*Vdot lenyap dari
            # persamaan gerak dan estimator tidak akan pernah menemukan R.
            peak_p = max(peak_p, target)
            peak_flow = max(peak_flow, q)
            if collect_waveform:
                wave.append((k * DT, target, q, float(self.plant.v.sum()) - v0))

        v_end_insp = self.plant.v.copy()
        # Plateau kuasi-statis: tekanan alveolar rata-rata tertimbang aliran nol.
        plateau = float(np.sum(self.plant._alveolar_pressure() * self.plant.w) /
                        np.sum(self.plant.w))

        for k in range(n_e):
            q, _ = self.plant.step(self.peep, DT)
            if collect_waveform:
                wave.append((t_insp + k * DT, self.peep, q, float(self.plant.v.sum()) - v0))

        regional = v_end_insp - v_start
        vt = float(regional.sum())

        # LMS: taksiran compliance ditarik ke compliance yang baru saja terukur,
        # lalu driving pressure napas berikutnya dihitung dari taksiran itu.
        # Ini setara skema Beda dkk. (Intensive Care Med 2010) untuk noisy PCV.
        if self.driving > 1e-6:
            c_measured = vt / self.driving
            self._c_est = (1.0 - self.mu) * self._c_est + self.mu * c_measured
            self._c_est = float(np.clip(self._c_est, 0.003, 0.130))
        self.driving = float(np.clip(vt_target / self._c_est, 2.0, 45.0))

        vt_alv = max(vt - self.plant.vd_anat, 0.0)
        shunt = self.plant.update_gas(vt_alv, t_tot, self.fio2)

        rec = BreathRecord(
            vt=vt, vt_target=vt_target, peak=peak_p, plateau=plateau,
            peep=self.peep, driving=plateau - self.peep,
            mp=mechanical_power(vt, peak_p, plateau, self.peep, 60.0 / t_tot),
            gi=gi_index(regional), flow_peak=peak_flow, t_tot=t_tot,
            paco2=self.plant.paco2, spo2=self.plant.spo2,
            recruited=self.plant.recruited_fraction, shunt=shunt,
            regional=regional,
        )
        return (rec, wave) if collect_waveform else rec


def mechanical_power(vt, peak, plateau, peep, rr):
    """Formula Gattinoni dkk. (Intensive Care Med 2016), satuan J/menit."""
    return 0.098 * rr * vt * (peak - 0.5 * (plateau - peep))


def gi_index(regional_vt):
    """
    Global Inhomogeneity index (Zhao dkk., Intensive Care Med 2009).

    Dihitung dari distribusi volume tidal antar kompartemen. Di ranjang pasien
    besaran ini datang dari EIT; di sini kompartemen twin berperan sebagai piksel.
    Nilai kecil berarti ventilasi merata.
    """
    v = np.asarray(regional_vt, dtype=float)
    total = v.sum()
    if total <= 1e-9:
        return 1.0
    return float(np.sum(np.abs(v - np.median(v))) / total)
