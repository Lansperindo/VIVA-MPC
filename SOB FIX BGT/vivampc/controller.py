"""
Lapis 3 dan 4: economic stochastic MPC dan safety supervisor.

Vektor keputusan -- inilah yang membedakan VIVA-MPC dari semua closed-loop
ventilation yang ada:

    u = [ VT_mean, PEEP, RR_mean, FiO2, CV, gamma, beta ]
                                        ^^^^^^^^^^^^^^^^
        tiga terakhir adalah BENTUK STATISTIK pola napas, dan di sinilah
        kebaruannya. ASV, INTELLiVENT, SmartCare, dan seluruh literatur RL
        ventilasi berhenti pada empat yang pertama. Ventilasi variabel
        konvensional menetapkan tiga yang terakhir sekali di awal lalu
        membekukannya.

Fungsi biaya bersifat economic, bukan tracking:

    J = w1*MP + w2*GI + w3*(PaCO2-target)^2 + w4*(SpO2 shortfall)^2 + w5*||du||^2

MP adalah metrik global (Gattinoni), GI adalah metrik regional dari EIT (Zhao).
Menggabungkan keduanya dalam satu horizon prediksi adalah pilar kebaruan kedua:
titrasi berpandu EIT yang ada sekarang bersifat step-trial heuristik, sedangkan
MPC ventilasi yang ada tidak pernah memakai informasi regional.

Optimisasi memakai cross-entropy method. Alasannya jujur: fungsi biaya di sini
stokastik (pola napas diacak) dan tidak mulus, sehingga metode berbasis gradien
tidak cocok. CEM bebas turunan, mudah diparalelkan, dan gampang dijelaskan saat
sidang.
"""

import numpy as np

from .variability import breath_pattern

# Batas KERAS. Angka-angka ini bukan selera, melainkan konsensus klinis:
# Pplat <= 30 dan driving pressure <= 15 (Amato dkk., NEJM 2015).
#
# Batas driving pressure dinyatakan pada DUA tingkat, dan ini penting. Ambang
# Amato <= 15 diturunkan dari ventilasi bervolume konstan, di mana setiap napas
# adalah napas rerata. Menerapkannya pada persentil ke-95 dari pola variabel
# berarti melarang variabilitas secara struktural: napas terbesar selalu melanggar,
# berapa pun kecilnya rerata. Karena itu rerata dibatasi 15 sesuai maksud aslinya,
# sementara ekor sebaran dibatasi terpisah pada 20 agar tetap ada pagar. Literatur
# ventilasi variabel memang menjalankan VT rerata 6 mL/kg dengan CV 30%, sehingga
# napas individual di sana mencapai sekitar 10 mL/kg.
#
# Mechanical power sengaja TIDAK dimasukkan ke sini. Tinjauan mutakhir menyatakan
# bukti yang ada belum mendukung penitrasian ventilasi ke ambang angka MP tertentu;
# ambang 16-18 J/menit bersifat asosiatif, bukan preskriptif. Lebih dari itu, pada
# ARDS berat tidak ada setting yang sekaligus membersihkan CO2 dan menahan MP di
# bawah 17, sehingga menjadikannya kendala keras hanya melahirkan kebuntuan.
# MP tetap menjadi suku biaya yang diminimalkan -- itu peran yang tepat baginya.
LIMITS = {
    "plateau_max": 30.0,
    "driving_max": 15.0,       # napas RERATA
    "driving_tail": 20.0,      # persentil ke-95
    "mp_soft": 17.0,
    "spo2_min": 90.0,
    "paco2_max": 65.0,
    "vt_max_ml_kg": 9.0,
}

BOUNDS = np.array([
    [0.22, 0.60],    # VT_mean, liter
    [5.0, 18.0],     # PEEP, cmH2O
    [12.0, 32.0],    # RR_mean, /menit
    [0.30, 0.90],    # FiO2
    [0.00, 0.40],    # CV
    [-0.80, 0.80],   # gamma (skewness)
    [0.00, 1.50],    # beta (eksponen fraktal)
])

VARIABILITY_IDX = slice(4, 7)


class VivaMPC:
    # Horizon 45 napas, sekitar 2.5 menit. Ini bukan angka sembarangan: manfaat
    # variabilitas menumpuk lewat ratchet rekrutmen yang konstanta waktunya
    # menit, bukan detik. Horizon yang lebih pendek dari konstanta waktu proses
    # membuat MPC secara struktural tidak mampu melihat imbalan dari keputusannya,
    # dan ia akan selalu memilih jalan yang murah di depan.
    def __init__(self, surrogate, weights=None, horizon=45, n_samples=24,
                 n_elite=7, n_iter=3, n_scenarios=3, weight_kg=70.0, seed=0,
                 fix_variability=None):
        self.model = surrogate
        self.H = horizon
        self.M = n_samples
        self.K = n_elite
        self.iters = n_iter
        self.scenarios = n_scenarios
        self.weight = weight_kg
        self.rng = np.random.default_rng(seed)

        # fix_variability = (cv, gamma, beta) mematok ketiga parameter bentuk,
        # mengubah VIVA-MPC menjadi MPC biasa yang hanya mengatur rerata. Inilah
        # ablasi yang menjawab pertanyaan pokok: seberapa besar sumbangan
        # mengoptimasi variabilitas, terpisah dari sumbangan MPC itu sendiri?
        self.bounds = BOUNDS.copy()
        self.fixed = fix_variability
        if fix_variability is not None:
            for i, v in enumerate(fix_variability):
                self.bounds[4 + i] = [v, v]

        self.w = weights or {
            "mp": 1.00,        # J/menit
            "gi": 28.0,        # GI tak berdimensi, perlu skala besar
            "paco2": 0.075,    # per mmHg^2
            "spo2": 0.55,      # per %^2 kekurangan
            "move": 0.60,
            "barrier": 45.0,
        }
        self.targets = {"paco2": 42.0, "spo2": 95.0}

        self.u = np.array([0.42, 8.0, 18.0, 0.50, 0.0, 0.0, 0.0])
        self.sigma = np.array([0.05, 2.0, 3.0, 0.07, 0.10, 0.30, 0.40])
        self.last_cost = None
        self.trace = []

    # ---- biaya ----------------------------------------------------------
    def _scenario_cost(self, u, state, rng):
        vt_m, peep, rr, fio2, cv, gamma, beta = u
        vt_seq, t_seq = breath_pattern(self.H, vt_m, rr, cv, gamma, beta, rng)
        out = self.model.rollout(state, vt_seq, t_seq, peep, fio2)

        w = self.w
        cost = w["mp"] * out["mp"] + w["gi"] * out["gi"]
        cost += w["paco2"] * (out["paco2"] - self.targets["paco2"]) ** 2
        cost += w["spo2"] * max(self.targets["spo2"] - out["spo2"], 0.0) ** 2
        cost += w["move"] * float(np.sum(((u - self.u) / (BOUNDS[:, 1] - BOUNDS[:, 0])) ** 2))

        # Barrier lunak di dalam biaya; batas keras tetap ditegakkan lapis 4.
        peak_vt = vt_m * (1.0 + 2.2 * cv)
        viol = (max(out["plateau"] - LIMITS["plateau_max"], 0.0)
                + max(out["driving"] - LIMITS["driving_max"], 0.0)
                + 0.5 * max(out["driving_p95"] - LIMITS["driving_tail"], 0.0)
                + 0.35 * max(out["mp"] - LIMITS["mp_soft"], 0.0)
                + max(1000.0 * peak_vt / self.weight - LIMITS["vt_max_ml_kg"], 0.0)
                + max(self.targets["spo2"] - 5.0 - out["spo2"], 0.0))
        cost += w["barrier"] * viol
        return cost

    def cost(self, u, state):
        """Rerata biaya lintas skenario -- inilah bagian stochastic dari MPC."""
        seeds = self.rng.integers(0, 2 ** 31 - 1, self.scenarios)
        return float(np.mean([
            self._scenario_cost(u, state, np.random.default_rng(int(s))) for s in seeds
        ]))

    # ---- optimisasi -----------------------------------------------------
    def solve(self, state):
        mean = self.u.copy()
        sigma = np.maximum(self.sigma, 0.02 * (self.bounds[:, 1] - self.bounds[:, 0]))

        for _ in range(self.iters):
            cand = self.rng.normal(mean, sigma, size=(self.M, len(mean)))
            cand = np.clip(cand, self.bounds[:, 0], self.bounds[:, 1])
            cand[0] = mean  # selalu pertahankan solusi sebelumnya sebagai kandidat

            costs = np.array([self.cost(c, state) for c in cand])
            elite = cand[np.argsort(costs)[: self.K]]
            mean = elite.mean(axis=0)
            sigma = 0.65 * sigma + 0.35 * (elite.std(axis=0) + 1e-4)

        mean = np.clip(mean, self.bounds[:, 0], self.bounds[:, 1])
        mean = self._polish_variability(mean, state)

        self.last_cost = self.cost(mean, state)
        floor = 0.015 * (self.bounds[:, 1] - self.bounds[:, 0])
        floor[VARIABILITY_IDX] *= 6.0   # jangan biarkan dimensi ini mengerut mati
        self.sigma = np.maximum(sigma, floor)
        return mean

    def _polish_variability(self, u, state):   # noqa: C901
        """
        Pencarian koordinat pada CV, gamma, dan beta setelah CEM.

        CEM bagus untuk parameter rerata yang saling terkopel kuat, tetapi ketiga
        parameter bentuk masuk ke biaya lewat kanal yang jauh lebih lemah dan
        lambat: lewat penumpukan rekrutmen sepanjang horizon, bukan lewat tekanan
        seketika. Dalam seleksi elit, kandidat ber-CV tinggi kerap tersingkir
        karena kebetulan pasangan VT dan PEEP-nya jelek, lalu sebaran CV mengerut
        ke nol dan tidak pernah pulih. Sekali sebaran itu mati, controller tidak
        akan pernah menemukan variabilitas lagi -- padahal justru itulah satu-
        satunya hal yang ingin dipelajari sistem ini.

        Poles koordinat memberi ketiganya satu kesempatan bersih pada titik kerja
        rerata yang sudah dipilih CEM. Murah, dan menutup mode kegagalan itu.
        """
        if self.fixed is not None:
            return u

        # PEEP dan VT ikut dipoles bersama parameter variabilitas, dan itu bukan
        # kemewahan. Rekrutmen lewat PEEP dan rekrutmen lewat variabilitas adalah
        # dua jalan menuju tujuan yang sama, jadi keduanya saling menggantikan.
        # Kalau CEM sudah terlanjur memilih PEEP tinggi, variabilitas memang tidak
        # lagi berguna di titik itu -- dan poles satu arah akan menyimpulkan
        # variabilitas tidak berguna, padahal yang terjadi hanyalah kita berdiri
        # di lembah yang salah. Dua putaran penuh membuat pasangan PEEP rendah
        # dengan CV tinggi punya kesempatan dinilai.
        grids = {
            4: np.linspace(self.bounds[4, 0], self.bounds[4, 1], 9),   # CV
            1: np.linspace(self.bounds[1, 0], self.bounds[1, 1], 7),   # PEEP
            0: np.linspace(self.bounds[0, 0], self.bounds[0, 1], 7),   # VT
            5: np.linspace(self.bounds[5, 0], self.bounds[5, 1], 5),   # gamma
            6: np.linspace(self.bounds[6, 0], self.bounds[6, 1], 5),   # beta
        }
        best = u.copy()
        best_cost = self.cost(best, state)

        for _round in range(2):
            improved = False
            for idx, grid in grids.items():
                if self.bounds[idx, 1] - self.bounds[idx, 0] < 1e-9:
                    continue
                trial_costs = []
                for value in grid:
                    trial = best.copy()
                    trial[idx] = value
                    trial_costs.append(self.cost(trial, state))
                j = int(np.argmin(trial_costs))
                if trial_costs[j] < best_cost - 1e-9:
                    best_cost = trial_costs[j]
                    best[idx] = grid[j]
                    improved = True
            if not improved:
                break

        return best

    def step(self, state, mechanics=None):
        if mechanics is not None:
            s = np.asarray(state.get("s", [1.0]))
            rec = float(np.sum(self.model.w * s)) if len(s) == self.model.n else 1.0
            self.model.update_from_estimator(mechanics, recruited_hint=rec)
        u_raw = self.solve(state)
        report = {}
        u_safe = safety_filter(u_raw, self.model, state, self.weight,
                               dead_space=self.model.vd, report=report,
                               bounds=self.bounds)
        self.u = u_safe
        self.trace.append({
            "u_raw": u_raw.copy(), "u_safe": u_safe.copy(),
            "cost": self.last_cost,
            "clipped": bool(np.any(np.abs(u_raw - u_safe) > 1e-6)),
            **report,
        })
        return u_safe


def safety_filter(u, model, state, weight_kg, dead_space=0.21, alpha=0.6,
                  max_pass=20, report=None, bounds=None):
    """
    Lapis 4. Proyeksi keluaran MPC ke himpunan aman, dalam semangat discrete-time
    control barrier function: untuk setiap kendala h(x) >= 0, aksi hanya diterima
    bila h tetap tidak negatif pada prediksi satu langkah ke depan.

    Ini SENGAJA dipisahkan dari fungsi biaya. Kalau keselamatan hanya berupa bobot
    penalti, optimizer boleh menukarnya dengan performa. Di sini tidak bisa.

    Hierarki prioritas
    ------------------
    Kendala ventilasi mekanis saling bertentangan, dan pada paru yang sangat kaku
    tidak ada setting yang memenuhi semuanya sekaligus. Karena itu urutan prioritas
    harus dinyatakan, bukan dibiarkan muncul dari bobot penalti:

      1. Ventilasi alveolar   -- tidal volume harus melampaui ruang rugi dengan
                                 margin. Ini mutlak. Napas yang lebih kecil dari
                                 ruang rugi tidak memindahkan gas sama sekali,
                                 berapa pun bagusnya angka driving pressure.
      2. Oksigenasi           -- SpO2 di atas ambang.
      3. Batas tekanan        -- plateau, driving pressure, mechanical power.

    Ketika prioritas 1 dan 3 bertabrakan, batas tekanan dilonggarkan ke plafon
    eskalasi dan peristiwa itu DICATAT. Inilah yang dilakukan klinisi pada
    hiperkapnia permisif; yang berbahaya bukan pelonggarannya, melainkan
    pelonggaran yang tidak terlihat.
    """
    u = np.array(u, dtype=float)
    bounds = BOUNDS if bounds is None else bounds
    rng = np.random.default_rng(12345)
    log = {"escalated": False, "binding": None, "passes": 0}

    vt_floor = max(bounds[0, 0], 1.35 * dead_space)
    plateau_cap, driving_cap = LIMITS["plateau_max"], LIMITS["driving_max"]

    for it in range(max_pass):
        log["passes"] = it + 1
        vt_m, peep, rr, fio2, cv, gamma, beta = u

        # Prioritas 1: ventilasi alveolar. Ditegakkan sebelum apa pun.
        if vt_m < vt_floor:
            u[0] = vt_floor
            continue

        # Volume napas terbesar yang masuk akal muncul dari pola variabel.
        vt_peak = vt_m * (1.0 + 2.2 * cv)
        if 1000.0 * vt_peak / weight_kg > LIMITS["vt_max_ml_kg"]:
            allowed = LIMITS["vt_max_ml_kg"] * weight_kg / 1000.0
            if cv > 0.02 and vt_m > 1e-6:
                u[4] = max(0.0, (allowed / vt_m - 1.0) / 2.2)
            else:
                u[0] = max(vt_floor, min(vt_m, allowed))
            continue

        vt_seq, t_seq = breath_pattern(12, vt_m, rr, cv, gamma, beta, rng)
        out = model.rollout(state, vt_seq, t_seq, peep, fio2)

        h = {
            "plateau": plateau_cap - out["plateau"],
            "driving": driving_cap - out["driving"],
            "driving_tail": (LIMITS["driving_tail"] + driving_cap
                             - LIMITS["driving_max"]) - out["driving_p95"],
            "spo2": out["spo2"] - LIMITS["spo2_min"],
            "paco2": LIMITS["paco2_max"] - out["paco2"],
        }
        worst = min(h, key=h.get)
        log["binding"] = worst
        if h[worst] >= 0.0:
            break

        gap = -h[worst] * alpha

        if worst == "paco2":
            if u[2] < bounds[2, 1] - 1e-6:
                u[2] = min(bounds[2, 1], u[2] + 1.5)
            else:
                # RR sudah mentok. Satu-satunya jalan menaikkan ventilasi
                # alveolar adalah menaikkan VT, dan itu menabrak batas tekanan.
                # Eskalasi terbatas, dicatat, tidak pernah melewati plafon kedua.
                log["escalated"] = True
                plateau_cap = min(LIMITS["plateau_max"] + 5.0, 35.0)
                driving_cap = min(LIMITS["driving_max"] + 5.0, 20.0)
                u[0] = min(bounds[0, 1],
                           min(u[0] + 0.015, LIMITS["vt_max_ml_kg"] * weight_kg / 1000.0))

        elif worst == "spo2":
            if u[3] < bounds[3, 1] - 1e-6:
                u[3] = min(bounds[3, 1], u[3] + 0.05)
            else:
                u[1] = min(bounds[1, 1], u[1] + 0.5)

        elif worst in ("plateau", "driving", "driving_tail"):
            # Kurangi variabilitas lebih dulu: ia yang menciptakan ekor tekanan,
            # dan memangkasnya tidak mengorbankan ventilasi semenit sama sekali.
            if u[4] > 0.01:
                u[4] = max(0.0, u[4] - 0.04)
            elif u[0] > vt_floor + 1e-6:
                u[0] = max(vt_floor, u[0] - max(0.008, 0.015 * gap))
            else:
                u[1] = max(bounds[1, 0], u[1] - 0.5)

        u = np.clip(u, bounds[:, 0], bounds[:, 1])
        u[0] = max(u[0], vt_floor)

    if report is not None:
        report.update(log)
    return np.clip(u, bounds[:, 0], bounds[:, 1])
