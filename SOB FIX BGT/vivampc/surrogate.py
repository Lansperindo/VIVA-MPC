"""
Model internal controller: surrogate tingkat-napas.

Twin fidelitas tinggi menyelesaikan ODE dengan langkah 4 ms. Satu rollout MPC
sepanjang 20 napas berarti puluhan ribu langkah, dan satu solusi MPC memerlukan
ratusan rollout. Itu tidak akan pernah selesai dalam 200 ms.

Jalan keluarnya adalah pendekatan multi-fidelity yang lazim pada digital twin paru:
controller memakai model yang jauh lebih kasar, yang melangkah satu NAPAS sekaligus
dan menyelesaikan mekanika secara kuasi-statis. Parameternya di-update dari estimator
MHE, sehingga surrogate tetap terikat pada pasien yang sebenarnya.

Ketidakcocokan dengan twin memang ada dan memang disengaja. Kalau controller tetap
bekerja baik di bawah ketidakcocokan itu, hasilnya jauh lebih meyakinkan daripada
controller yang mengoptimasi model dirinya sendiri.
"""

import numpy as np

from .ventilator import mechanical_power, gi_index


class BreathSurrogate:
    def __init__(self, n_comp=20, weights=None, p_open=None, p_close=None,
                 c_total=40.0, e2_frac=0.25, r_airway=10.0,
                 k_open=0.016, k_close=0.022, vco2=0.20, vd=0.21):
        self.n = n_comp
        self.w = np.full(n_comp, 1.0 / n_comp) if weights is None else np.asarray(weights)

        # Prior lognormal untuk tekanan pembukaan. Controller TIDAK tahu sebaran
        # yang sebenarnya pada twin -- ini prior, bukan salinan. Yang penting
        # bentuknya benar: ada ekor unit bertekanan tinggi, sehingga rollout bisa
        # melihat bahwa napas besar sesekali membuka unit yang napas rerata tidak
        # pernah sentuh. Tanpa ekor itu, optimizer akan selalu memilih CV = 0.
        if p_open is None:
            q = (np.arange(n_comp) + 0.5) / n_comp
            from scipy.special import erfinv
            self.p_open = 20.0 * np.exp(0.42 * np.sqrt(2.0) * erfinv(2 * q - 1))
        else:
            self.p_open = np.asarray(p_open)
        self.p_close = 0.32 * self.p_open if p_close is None else np.asarray(p_close)
        self.c_total = c_total
        self.e2_frac = e2_frac
        self.r_airway = r_airway
        self.k_open = k_open
        self.k_close = k_close
        self.vco2 = vco2
        self.vd = vd

    def update_from_estimator(self, mech, recruited_hint=None):
        """
        Sinkronkan surrogate dengan keluaran MHE.

        C_static dari MHE adalah compliance EFEKTIF pada kondisi rekrutmen saat ini,
        bukan compliance paru yang terbuka penuh. Kalau nilai itu langsung dipakai
        lalu di dalam rollout dikalikan lagi dengan fraksi rekrutmen, compliance
        terhitung dua kali kecil dan controller akan mengira paru jauh lebih kaku
        daripada kenyataannya.
        """
        self.r_airway = float(np.clip(mech["R"], 2.0, 60.0))
        c_eff = float(np.clip(mech["C_static"], 6.0, 90.0))
        rec = float(np.clip(recruited_hint if recruited_hint else 1.0, 0.15, 1.0))
        self.c_total = float(np.clip(c_eff / rec, 8.0, 120.0))
        e1, e2 = max(mech["E1"], 1e-6), mech["E2"]
        self.e2_frac = float(np.clip(e2 * 0.5 / (e1 + e2 * 0.5), 0.0, 0.7))

    def rollout(self, state, vt_seq, t_seq, peep, fio2):
        """
        Jalankan barisan napas. state = dict(s, paco2, pao2).
        Mengembalikan ringkasan biaya dan state akhir.
        """
        s = np.array(state["s"], dtype=float)
        paco2 = float(state["paco2"])
        pao2 = float(state["pao2"])

        mp_sum = gi_sum = 0.0
        peaks, plateaus = [], []
        n = len(vt_seq)

        for vt, t_tot in zip(vt_seq, t_seq):
            s_eff = np.maximum(s, 0.02)
            # Compliance efektif hanya dari bagian yang terekrut.
            c_open = self.c_total * float(np.sum(self.w * s_eff)) / 1000.0
            c_open = max(c_open, 0.002)

            e_lin = 1.0 / c_open
            plateau = peep + vt * e_lin * (1.0 + self.e2_frac * vt / 0.5)
            flow = vt / max(t_tot * 0.33, 0.15)
            peak = plateau + self.r_airway * flow

            # Distribusi volume mengikuti compliance regional yang terbuka.
            share = self.w * s_eff
            share = share / max(share.sum(), 1e-9)
            regional = share * vt

            # Rekrutmen per napas. Laju harus SEPADAN dengan laju pada twin.
            #
            # Versi pertama modul ini memakai laju 19 kali lebih cepat, dan
            # akibatnya fatal namun tidak kentara: rekrutmen jenuh dalam dua
            # napas, sehingga rollout memperkirakan GI yang sama untuk CV berapa
            # pun. Optimizer lalu menyimpulkan variabilitas tidak berguna dan
            # selalu memilih CV = 0 -- persis kebalikan dari perilaku twin.
            # Model internal yang terlalu optimistis tentang rekrutmen membuat
            # controller buta terhadap satu-satunya hal yang ingin ia pelajari.
            t_insp = t_tot / 3.0
            t_exp = t_tot - t_insp
            over = np.maximum(peak - self.p_open, 0.0)
            under = np.maximum(self.p_close - peep, 0.0)
            s = np.clip(s + self.k_open * over * t_insp
                        - self.k_close * under * t_exp, 0.02, 1.0)

            mp_sum += mechanical_power(vt, peak, plateau, peep, 60.0 / t_tot)
            gi_sum += gi_index(regional)
            peaks.append(peak)
            plateaus.append(plateau)

            va = max(vt - self.vd, 0.0) * 60.0 / t_tot
            ss = np.clip(863.0 * self.vco2 / max(va, 0.05), 12.0, 130.0)
            paco2 += (1.0 - np.exp(-t_tot / 150.0)) * (ss - paco2)

        collapsed = 1.0 - float(np.sum(self.w * s))
        shunt = float(np.clip(0.04 + 0.55 * collapsed, 0.02, 0.60))
        pao2_ideal = fio2 * 713.0 - paco2 / 0.8
        pao2 = pao2_ideal * (1.0 - shunt) ** 1.6
        spo2 = 100.0 / (23400.0 / (max(pao2, 1.0) ** 3 + 150.0 * max(pao2, 1.0)) + 1.0)

        # Kendala dilaporkan sebagai kuantil, bukan maksimum.
        #
        # Pada ventilasi variabel, memaksa SETIAP napas patuh berarti napas
        # terbesar dalam horizon yang menentukan segalanya, dan optimizer akan
        # selalu memilih CV = 0 untuk menghilangkan ekor itu. Chance constraint
        # menanyakan hal yang benar: berapa fraksi napas yang boleh melampaui
        # batas. Inilah yang membuat kata "stochastic" pada stochastic MPC punya
        # isi, bukan sekadar label.
        plateaus = np.asarray(plateaus)
        peaks = np.asarray(peaks)
        plat_q = float(np.percentile(plateaus, 95))
        plat_mean = float(plateaus.mean())

        return {
            "mp": mp_sum / n, "gi": gi_sum / n,
            "peak": float(np.percentile(peaks, 95)), "peak_max": float(peaks.max()),
            "plateau": plat_q, "plateau_max": float(plateaus.max()),
            "plateau_mean": plat_mean,
            "driving": plat_mean - peep,        # napas rerata
            "driving_p95": plat_q - peep,       # ekor sebaran
            "paco2": paco2, "pao2": pao2, "spo2": spo2,
            "s": s, "recruited": float(np.sum(self.w * s)),
        }
