"""Buat grafik hasil."""
import json
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

INK, GRID = "#1C262C", "#D7DEE2"
COL = {"ARDSNet": "#6E8894", "ASV-like": "#4B7BA8",
       "Noisy PCV (CV 30%)": "#D98324", "VIVA-MPC": "#1F7A5C"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": INK,
    "axes.labelcolor": INK, "text.color": INK, "xtick.color": INK,
    "ytick.color": INK, "axes.spines.top": False, "axes.spines.right": False,
    "figure.facecolor": "white", "axes.grid": True, "grid.color": GRID,
    "grid.linewidth": 0.6, "axes.axisbelow": True,
})

rows = json.load(open(str(ROOT / "results.json")))["rows"]
par = json.load(open(str(ROOT / "pareto.json")))["rows"]

order = ["sehat", "ards_ringan", "ards_sedang", "ards_berat",
         "obstruktif", "derekrutmen"]
labels = {r["scenario"]: r["label"] for r in rows}
ctrls = ["ARDSNet", "ASV-like", "Noisy PCV (CV 30%)", "VIVA-MPC"]
get = lambda sc, c, k: next((r[k] for r in rows
                             if r["scenario"] == sc and r["controller"] == c), np.nan)

# ---------- Gambar 1: matriks lintas skenario ----------
fig, axes = plt.subplots(1, 3, figsize=(11.6, 3.5))
metrics = [("mp_mean", "Mechanical power  (J/menit)", None),
           ("gi_mean", "GI index  (rendah = merata)", None),
           ("driving_mean", "Driving pressure  (cmH$_2$O)", 15.0)]

x = np.arange(len(order))
for ax, (key, title, limit) in zip(axes, metrics):
    for i, c in enumerate(ctrls):
        vals = [get(sc, c, key) for sc in order]
        ax.bar(x + (i - 1.5) * 0.2, vals, 0.19, label=c, color=COL[c])
    if limit:
        ax.axhline(limit, color="#B03A2E", lw=1, ls="--", zorder=3)
        ax.text(len(order) - 0.4, limit + 0.5, "batas 15", color="#B03A2E", fontsize=7.5)
    ax.set_xticks(x)
    ax.set_xticklabels([labels[s] for s in order], rotation=28, ha="right", fontsize=8)
    ax.set_title(title, fontsize=9.5, loc="left", pad=8)

axes[0].legend(frameon=False, fontsize=7.8, loc="upper left")
fig.suptitle("Matriks eksperimen: enam kondisi paru, empat strategi kendali",
             fontsize=11, x=0.008, ha="left", y=1.0)
fig.tight_layout(rect=[0, 0, 1, 0.94])
fig.savefig(ROOT / "gambar1_matriks.png", dpi=170)

# ---------- Gambar 2: dosis variabilitas yang dipilih ----------
fig, (a1, a2) = plt.subplots(1, 2, figsize=(10.4, 3.6),
                             gridspec_kw={"width_ratios": [1, 1.15]})

cv_sel = [get(sc, "VIVA-MPC", "vt_cv_realised") for sc in order]
bars = a1.bar(x, cv_sel, 0.55, color=COL["VIVA-MPC"])
a1.axhline(0.30, color="#D98324", lw=1.2, ls="--")
a1.text(len(order) - 0.45, 0.313, "dosis tetap literatur (0,30)",
        color="#D98324", fontsize=7.8, ha="right")
a1.set_xticks(x)
a1.set_xticklabels([labels[s] for s in order], rotation=28, ha="right", fontsize=8)
a1.set_ylabel("CV tidal volume yang dipilih")
a1.set_title("Dosis variabilitas berbeda-beda menurut kondisi paru",
             fontsize=9.5, loc="left", pad=8)
for b, v in zip(bars, cv_sel):
    a1.text(b.get_x() + b.get_width() / 2, v + 0.008, f"{v:.2f}",
            ha="center", fontsize=7.5)

for c in ctrls:
    gi = [get(sc, c, "gi_mean") for sc in order]
    mp = [get(sc, c, "mp_mean") for sc in order]
    a2.scatter(gi, mp, s=42, color=COL[c], label=c, zorder=3,
               edgecolor="white", linewidth=0.7)
a2.set_xlabel("GI index")
a2.set_ylabel("Mechanical power  (J/menit)")
a2.set_title("Bidang trade-off: kiri-bawah lebih baik", fontsize=9.5, loc="left", pad=8)
a2.legend(frameon=False, fontsize=7.8)
fig.tight_layout()
fig.savefig(ROOT / "gambar2_dosis.png", dpi=170)

# ---------- Gambar 3: ablasi Pareto ----------
fig, ax = plt.subplots(figsize=(6.6, 4.4))
VC = {"CV=0": "#6E8894", "CV=0.15": "#4B7BA8",
      "CV=0.30": "#D98324", "CV bebas": "#1F7A5C"}
for v, col in VC.items():
    pts = [(r["gi_mean"], r["mp_mean"]) for r in par if r["variant"] == v]
    if not pts:
        continue
    gi, mp = zip(*pts)
    ax.scatter(gi, mp, s=52, color=col, label=v, zorder=3,
               edgecolor="white", linewidth=0.8)
ax.set_xlabel("GI index")
ax.set_ylabel("Mechanical power  (J/menit)")
ax.set_title("Ablasi pada ARDS sedang: mesin identik, hanya\n"
             "variabilitas yang dipatok atau dibebaskan",
             fontsize=10, loc="left", pad=10)
ax.legend(frameon=False, fontsize=8.5, title="empat bobot GI per varian",
          title_fontsize=8)
fig.tight_layout()
fig.savefig(ROOT / "gambar3_ablasi.png", dpi=170)

print("tiga gambar tersimpan")
for sc in order:
    print(f"{labels[sc]:<24s} CV={get(sc,'VIVA-MPC','vt_cv_realised'):.3f}")
