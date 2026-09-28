"""
Digital twin paru fidelitas tinggi -- berperan sebagai "pasien" dalam simulasi.

Struktur:
  * N kompartemen paralel, masing-masing dengan resistansi cabang sendiri, di
    belakang satu resistansi jalan napas bersama.
  * Elastance bergantung volume, E(V) = E1 + E2*V, sehingga overdistensi muncul
    secara alami sebagai pengerasan pada volume tinggi (Kano, Bersten, Carvalho).
  * Rekrutmen/derekrutmen bergantung waktu ala Bates & Irvin (J Appl Physiol 2002):
    kompartemen tidak membuka seketika saat tekanan melewati ambang, melainkan
    membuka dengan laju yang sebanding dengan seberapa jauh tekanan melampaui
    ambang itu. Inilah yang membuat variabilitas napas bisa "menabung" rekrutmen.
  * Pertukaran gas tiga kompartemen: ruang rugi, kompartemen ideal, dan shunt yang
    besarnya ditentukan oleh fraksi paru yang masih kolaps.

Perhatikan: controller TIDAK pernah melihat isi kelas ini. Controller memakai model
tingkat-napas yang jauh lebih kasar (lihat surrogate.py). Ketidakcocokan antara
keduanya disengaja -- itulah ujian kekukuhan yang sesungguhnya.
"""

import numpy as np

PATM = 760.0
PH2O = 47.0
RQ = 0.8


class LungPlant:
    def __init__(self, n_comp=20, c_total=40.0, r_airway=6.0, e2_frac=0.25,
                 p_open_mean=18.0, p_open_sd=6.0, close_ratio=0.32,
                 shunt_floor=0.04, vco2=0.20, weight_kg=70.0,
                 k_open=0.016, k_close=0.022, seed=0):
        """
        c_total    compliance sistem pernapasan saat rekrutmen penuh, mL/cmH2O
        r_airway   resistansi jalan napas bersama, cmH2O/L/s
        e2_frac    porsi elastance yang bergantung volume (proxy %E2)
        p_open_*   median dan sebaran tekanan pembukaan kompartemen (lognormal)
        close_ratio tekanan penutupan sebagai fraksi tekanan pembukaan
        """
        rng = np.random.default_rng(seed)
        self.n = n_comp
        self.weight = weight_kg

        # Bobot kompartemen dibuat sedikit tidak seragam supaya GI index punya arti.
        w = rng.uniform(0.7, 1.3, n_comp)
        self.w = w / w.sum()

        self.c_comp = c_total * self.w / 1000.0            # L/cmH2O per kompartemen
        self.e1 = 1.0 / self.c_comp
        # e2 dikalibrasi terhadap volume paru total rujukan 1.0 L, bukan terhadap
        # tidal volume. Kalau dirujukkan ke tidal volume, suku nonlinier ikut
        # terhitung dua kali pada volume yang sudah dinaikkan PEEP dan plateau
        # meledak ke angka yang tidak masuk akal.
        v_ref = 1.0 * self.w
        self.e2 = e2_frac * self.e1 / ((1.0 - e2_frac) * v_ref)
        self.r_comp = r_airway * 1.2 / (self.w * n_comp)   # cabang, paralel
        self.r_airway = r_airway

        # Tekanan pembukaan lognormal dengan ekor panjang, bukan normal.
        #
        # Ini bukan pemanis. Kalau sebarannya sempit, setiap napas membuka semua
        # unit yang bisa dibuka dan tidak ada yang tersisa untuk dikerjakan napas
        # besar sesekali -- manfaat ventilasi variabel lenyap dari model, padahal
        # itu justru fenomena yang mau dipelajari. Ekor panjang membuat sebagian
        # unit hanya terbuka oleh napas di atas rerata, dan di situlah pertidaksamaan
        # Jensen bekerja (Brewster, Graham & Mutch, J R Soc Interface 2005).
        sigma = np.clip(p_open_sd / max(p_open_mean, 1.0), 0.05, 0.95)
        grad = np.linspace(-0.55, 0.55, n_comp)          # gradien gravitasi
        z = rng.normal(0.0, 1.0, n_comp)
        self.p_open = p_open_mean * np.exp(sigma * (z + grad))
        self.p_open = np.clip(self.p_open, 3.0, 55.0)

        # Histeresis proporsional: unit yang butuh tekanan tinggi untuk membuka
        # tetap terbuka jauh di bawah tekanan itu. Inilah ratchet yang membuat
        # napas besar sesekali menabung rekrutmen alih-alih membuangnya.
        self.p_close = close_ratio * self.p_open
        self.k_open = k_open
        self.k_close = k_close

        self.shunt_floor = shunt_floor
        self.vco2 = vco2
        self.vd_anat = 2.2e-3 * weight_kg + 0.055

        self.reset()

    def reset(self, peep=5.0):
        self.v = np.zeros(self.n)
        self.s = np.clip((peep - self.p_close) / 8.0, 0.02, 1.0)
        self.paco2 = 40.0
        self.pao2 = 90.0
        self.peep = peep
        self._settle(peep)

    def _settle(self, peep, seconds=6.0, dt=0.002):
        for _ in range(int(seconds / dt)):
            self.step(peep, dt)

    # ---- mekanika -------------------------------------------------------
    def _alveolar_pressure(self):
        """Elastance bergantung volume pada jaringan yang memang terisi."""
        return (self.e1 + self.e2 * self.v) * self.v

    def _branch_resistance(self):
        """
        Derekrutmen dimodelkan sebagai penyempitan saluran, bukan pengerasan jaringan.

        Ini pilihan yang disengaja. Kalau derekrutmen dimodelkan sebagai elastance
        yang membesar, konstanta waktu kompartemen menyusut sampai di bawah langkah
        waktu integrator dan simulasi meledak. Lebih dari itu, secara fisiologi unit
        yang kolaps memang tidak menerima aliran -- ia tertutup, bukan kaku. Dengan
        R ~ 1/s^2, unit yang hampir tertutup mengisi sangat lambat sehingga dalam
        satu napas ia praktis tidak ikut berventilasi; persis perilaku yang membuat
        rekrutmen bergantung waktu (Bates & Irvin 2002).
        """
        return self.r_comp / np.maximum(self.s, 0.02) ** 2

    def step(self, p_airway_opening, dt):
        """Maju satu langkah waktu. Mengembalikan (flow total L/s, tekanan jalan napas)."""
        p_alv = self._alveolar_pressure()
        r_eff = self._branch_resistance()
        g = np.sum(1.0 / r_eff)
        a = np.sum(p_alv / r_eff)

        p_aw = (p_airway_opening + self.r_airway * a) / (1.0 + self.r_airway * g)
        q = (p_aw - p_alv) / r_eff
        self.v = np.clip(self.v + q * dt, 0.0, 6.0 * self.w)

        # Rekrutmen bergantung waktu: laju sebanding dengan kelebihan tekanan.
        over = p_aw - self.p_open
        under = self.p_close - p_aw
        ds = np.where(over > 0, self.k_open * over, 0.0) * dt
        ds -= np.where(under > 0, self.k_close * under, 0.0) * dt
        self.s = np.clip(self.s + ds, 0.02, 1.0)

        return float(q.sum()), float(p_aw)

    # ---- pertukaran gas -------------------------------------------------
    def update_gas(self, vt_alveolar, breath_time, fio2):
        """Perbarui PaCO2 dan PaO2 setelah satu napas selesai."""
        va_min = max(vt_alveolar, 0.0) * 60.0 / max(breath_time, 0.1)

        # Simpanan CO2 tubuh, orde 2-3 menit -- ini yang membuat PaCO2 tidak
        # melompat seketika saat setting berubah.
        tau = 150.0
        paco2_ss = 863.0 * self.vco2 / max(va_min, 0.05)
        alpha = 1.0 - np.exp(-breath_time / tau)
        self.paco2 += alpha * (np.clip(paco2_ss, 12.0, 130.0) - self.paco2)

        collapsed = 1.0 - float(np.sum(self.w * self.s))
        shunt = np.clip(self.shunt_floor + 0.55 * collapsed, 0.02, 0.60)

        pao2_ideal = fio2 * (PATM - PH2O) - self.paco2 / RQ
        cc = self._o2_content(self._sat(pao2_ideal), pao2_ideal)
        cv_blood = cc - 0.045          # selisih arteriovena tipikal
        ca = shunt * cv_blood + (1.0 - shunt) * cc
        self.pao2 = self._invert_content(ca)
        return shunt

    @staticmethod
    def _sat(po2):
        p = max(po2, 1.0)
        return 1.0 / (23400.0 / (p ** 3 + 150.0 * p) + 1.0)

    @staticmethod
    def _o2_content(sat, po2):
        return 1.34 * 0.15 * sat + 0.00003 * po2

    def _invert_content(self, ca):
        lo, hi = 10.0, 650.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if self._o2_content(self._sat(mid), mid) < ca:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    @property
    def spo2(self):
        return 100.0 * self._sat(self.pao2)

    @property
    def recruited_fraction(self):
        return float(np.sum(self.w * self.s))

    def state_snapshot(self):
        return {
            "recruited": self.recruited_fraction,
            "paco2": self.paco2,
            "pao2": self.pao2,
            "spo2": self.spo2,
        }
