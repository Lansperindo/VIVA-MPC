"""
Generator pola napas variabel dengan tiga parameter bentuk yang dapat dikendalikan.

Inilah inti kebaruan VIVA-MPC. Literatur ventilasi variabel (Mutch 2000, Suki 1998,
Gama de Abreu 2008-2018) selalu menetapkan pola variabilitas SEBELUM ventilasi dimulai:
CV tetap (biasanya 30%), distribusi Gaussian, dan tanpa struktur korelasi temporal yang
dikendalikan. Controller LMS adaptif Beda dkk. (Intensive Care Med 2010) melacak pola
tersebut, tetapi tidak memilihnya.

Modul ini memparameterkan pola itu menjadi tiga bilangan yang bisa dioptimasi:

    cv    koefisien variasi tidal volume          [0, 0.45]
    gamma skewness marginal distribusi            [-0.9, 0.9]
    beta  eksponen spektral korelasi antar-napas  [0, 1.6]
          beta = 0   derau putih (tanpa memori antar-napas)
          beta = 1   derau 1/f, mendekati napas spontan sehat
          beta = 2   gerak Brown (terlalu lambat, non-stasioner)

Metode: sintesis spektral untuk struktur korelasi, lalu transformasi kopula Gaussian
ke distribusi skew-normal untuk skewness. Urutan ini penting -- transformasi marginal
dilakukan secara rank-preserving sehingga struktur korelasi hampir tidak rusak.
"""

import numpy as np
from scipy import special


def _fractal_gaussian(n, beta, rng):
    """Deret Gaussian ternormalisasi dengan densitas spektral daya S(f) ~ f^(-beta)."""
    if n < 4:
        return rng.standard_normal(n)

    # Oversample lalu potong: menghindari periodisitas palsu dari FFT melingkar.
    m = int(2 ** np.ceil(np.log2(n * 4)))
    freqs = np.fft.rfftfreq(m, d=1.0)
    amp = np.zeros_like(freqs)
    amp[1:] = freqs[1:] ** (-beta / 2.0)
    amp[0] = 0.0  # buang komponen DC; rerata diatur terpisah

    phase = rng.uniform(0, 2 * np.pi, size=freqs.shape)
    spectrum = amp * np.exp(1j * phase)
    series = np.fft.irfft(spectrum, n=m)[:n]

    sd = series.std()
    return series / sd if sd > 1e-12 else series


def _skewnormal_shape(gamma):
    """Konversi skewness target ke parameter bentuk alpha distribusi skew-normal."""
    g = float(np.clip(gamma, -0.985, 0.985))
    if abs(g) < 1e-6:
        return 0.0
    # Inversi analitik dari hubungan skewness-delta pada skew-normal.
    c = (2.0 * abs(g) / (4.0 - np.pi)) ** (1.0 / 3.0)
    delta = np.sign(g) * np.sqrt(np.pi / 2.0) * c / np.sqrt(1.0 + c ** 2)
    delta = np.clip(delta, -0.9999, 0.9999)
    return delta / np.sqrt(1.0 - delta ** 2)


def _skewnormal_quantile(p, alpha, grid=4096):
    """Kuantil skew-normal baku (mean 0, varians 1) lewat interpolasi CDF numerik."""
    if abs(alpha) < 1e-9:
        return np.sqrt(2.0) * special.erfinv(2.0 * np.clip(p, 1e-9, 1 - 1e-9) - 1.0)

    x = np.linspace(-9.0, 9.0, grid)
    pdf = 2.0 * np.exp(-0.5 * x ** 2) / np.sqrt(2 * np.pi) * 0.5 * (
        1.0 + special.erf(alpha * x / np.sqrt(2.0))
    )
    cdf = np.cumsum(pdf)
    cdf /= cdf[-1]
    raw = np.interp(np.clip(p, 1e-9, 1 - 1e-9), cdf, x)

    delta = alpha / np.sqrt(1.0 + alpha ** 2)
    mu = np.sqrt(2.0 / np.pi) * delta
    sd = np.sqrt(1.0 - mu ** 2)
    return (raw - mu) / sd


def _iaaft(target_values, target_amplitude, n_iter=None):
    """
    Iterative Amplitude Adjusted Fourier Transform (Schreiber & Schmitz, PRL 1996).

    Kopula Gaussian biasa merusak spektrum ketika skewness besar: transformasi
    marginal yang nonlinier menggeser energi antar frekuensi. IAAFT menyelesaikan
    itu dengan memaksakan dua kendala secara bergantian sampai keduanya terpenuhi:
    distribusi marginal persis sama dengan target, dan amplitudo spektral persis
    sama dengan target. Hasilnya CV, skewness, dan beta semuanya terwujud.
    """
    if n_iter is None:
        # Horizon MPC hanya belasan napas; struktur spektral di sana nyaris
        # tidak punya ruang untuk terbentuk, jadi iterasi penuh cuma membakar
        # waktu. Deret panjang untuk plant tetap mendapat iterasi penuh.
        n_iter = int(np.clip(len(target_values) // 8, 6, 60))
    sorted_target = np.sort(target_values)
    series = np.random.default_rng(0).permutation(target_values)

    for _ in range(n_iter):
        spec = np.fft.rfft(series)
        phase = np.angle(spec)
        series = np.fft.irfft(target_amplitude * np.exp(1j * phase),
                              n=len(series))
        order = np.argsort(np.argsort(series))
        new = sorted_target[order]
        if np.allclose(new, series, atol=1e-10):
            series = new
            break
        series = new

    return series


def breath_pattern(n_breaths, vt_mean, rr_mean, cv=0.0, gamma=0.0, beta=0.0,
                   rng=None, vt_floor=0.35, vt_ceiling=2.0):
    """
    Bangkitkan barisan tidal volume dan waktu napas.

    Ventilasi semenit dijaga konstan: ketika satu napas lebih besar dari rerata,
    napas itu diberi durasi lebih panjang secara proporsional. Tanpa ini, menaikkan
    CV akan diam-diam menaikkan ventilasi semenit dan setiap perbandingan menjadi
    tidak adil.

    Mengembalikan
    -------------
    vt    (n,) tidal volume per napas, liter
    t_tot (n,) durasi total tiap napas, detik
    """
    rng = np.random.default_rng() if rng is None else rng

    if cv < 1e-6:
        vt = np.full(n_breaths, vt_mean)
        return vt, np.full(n_breaths, 60.0 / rr_mean)

    z = _fractal_gaussian(n_breaths, beta, rng)

    # Marginal target: kuantil skew-normal pada peringkat empiris. Memakai
    # peringkat, bukan CDF normal teoretis, supaya distribusi tepat sasaran
    # walau z belum ergodik pada panjang deret yang pendek.
    ranks = np.argsort(np.argsort(z))
    u = (ranks + 0.5) / n_breaths
    shaped = _skewnormal_quantile(u, _skewnormal_shape(gamma))
    shaped = (shaped - shaped.mean()) / (shaped.std() + 1e-12)

    if beta > 1e-6 and n_breaths >= 16:
        shaped = _iaaft(shaped, np.abs(np.fft.rfft(z)))
        shaped = (shaped - shaped.mean()) / (shaped.std() + 1e-12)

    vt = vt_mean * (1.0 + cv * shaped)
    vt = np.clip(vt, vt_floor * vt_mean, vt_ceiling * vt_mean)
    vt *= vt_mean / vt.mean()  # pulihkan rerata setelah clipping

    minute_volume = vt_mean * rr_mean
    t_tot = 60.0 * vt / minute_volume
    return vt, np.clip(t_tot, 0.8, 8.0)


def realised_moments(vt):
    """Momen yang benar-benar terwujud -- untuk memverifikasi generator, bukan hiasan."""
    m, s = vt.mean(), vt.std()
    cv = s / m if m > 0 else 0.0
    skew = float(np.mean(((vt - m) / s) ** 3)) if s > 1e-12 else 0.0
    return {"mean": float(m), "cv": float(cv), "skewness": skew}


def spectral_exponent(vt):
    """Estimasi eksponen beta dari deret, lewat regresi log-log pada periodogram."""
    x = vt - vt.mean()
    n = len(x)
    if n < 32:
        return float("nan")
    power = np.abs(np.fft.rfft(x)) ** 2
    freqs = np.fft.rfftfreq(n, d=1.0)
    lo, hi = 1, max(2, n // 8)
    fit = np.polyfit(np.log(freqs[lo:hi]), np.log(power[lo:hi] + 1e-30), 1)
    return float(-fit[0])
