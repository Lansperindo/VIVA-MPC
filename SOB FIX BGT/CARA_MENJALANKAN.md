# Menjalankan di VS Code

## Sekali di awal

1. Buka folder ini di VS Code: **File → Open Folder**.
2. Pasang ekstensi **Python** dari Microsoft (ikon kotak-kotak di bilah kiri,
   cari "Python").
3. Buat lingkungan virtual. Tekan `Ctrl+Shift+P` (`Cmd+Shift+P` di Mac), ketik
   **Python: Create Environment** → pilih **Venv** → pilih interpreter Python
   Anda → centang `requirements.txt` saat ditawarkan.

   Kalau lebih suka terminal (`Ctrl+` `` ` ``):

   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS / Linux:
   source .venv/bin/activate

   pip install -r requirements.txt
   ```

## Menjalankan

Buka panel **Run and Debug** (`Ctrl+Shift+D`). Di dropdown atas sudah tersedia
empat konfigurasi, jalankan berurutan:

| Konfigurasi | Lama | Menghasilkan |
|---|---|---|
| 1 — Cek instalasi | beberapa detik | verifikasi semua komponen |
| 2 — Ablasi variabilitas | ~4 menit | `pareto.json` |
| 3 — Matriks eksperimen | ~5 menit | `results.json`, `traces.npy` |
| 4 — Buat gambar | beberapa detik | tiga berkas `gambar*.png` |

**Jalankan nomor 1 lebih dulu.** Ia selesai dalam hitungan detik dan memastikan
numpy serta scipy terpasang benar, sehingga Anda tidak menunggu lima menit hanya
untuk menemukan `ModuleNotFoundError`.

Nomor 4 membutuhkan `results.json` dan `pareto.json`, jadi nomor 2 dan 3 harus
sudah selesai.

Lewat terminal juga bisa:

```bash
python cek_instalasi.py
python run_pareto.py
python run_experiments.py
python make_figures.py
```

## Simulator web

`viva-mpc-simulator.html` tidak butuh Python sama sekali. Klik dua kali berkasnya,
atau klik kanan di VS Code → **Open with Live Server** kalau ekstensi itu terpasang.

## Bereksperimen sendiri

Tempat-tempat yang paling menarik untuk diutak-atik:

| Yang ingin diubah | Berkas | Cari |
|---|---|---|
| Bobot fungsi biaya | `vivampc/controller.py` | `self.w = weights or` |
| Batas keselamatan | `vivampc/controller.py` | `LIMITS = {` |
| Panjang horizon | `vivampc/controller.py` | `horizon=45` |
| Kondisi paru | `vivampc/scenarios.py` | `SCENARIOS = {` |
| Fisiologi twin | `vivampc/plant.py` | `class LungPlant` |
| Kalibrasi surrogate | `vivampc/surrogate.py` | `k_open`, `k_close` |

Yang paling layak dikerjakan lebih dulu adalah kalibrasi surrogate — lihat bagian 4
dan 7 di `LAPORAN.md`.

## Kalau macet

- **`ModuleNotFoundError: vivampc`** — VS Code menjalankan dari folder yang salah.
  Pastikan folder yang dibuka adalah folder yang berisi `cek_instalasi.py`, bukan
  folder induknya.
- **Grafik tidak muncul** — memang tidak muncul di layar. Skripnya menyimpan berkas
  PNG ke folder yang sama, karena backend matplotlib disetel ke `Agg`.
- **Terasa lambat** — turunkan `MINUTES` di `run_experiments.py` menjadi 5, atau
  kurangi `SEEDS` menjadi `[1]`.


## Membangun ulang paru di Blender

Skrip `buat_paru_blender.py` memakai `bpy`, modul yang hanya ada di dalam Blender, jadi
**tidak bisa** dijalankan dengan `python` biasa. Pasang Blender (gratis, blender.org), lalu:

```bash
# Linux / macOS
blender -b --python buat_paru_blender.py

# Windows (sesuaikan versinya)
"C:\Program Files\Blender Foundation\Blender 4.0\blender.exe" -b --python buat_paru_blender.py
```

Hasilnya `paru_blender.obj` di folder yang sama. Tanam ke simulator dengan Python biasa:

```bash
python tanam_mesh.py
```

Semua proporsi paru ada di bagian atas `buat_paru_blender.py` sebagai angka yang bisa diubah:
`HALF`, `DEEP`, `SUP_SLOPE`, `INF_SLOPE`, `OBLIQ_Z`, `SIDE`.

Cara lain tanpa terminal: buka Blender, tab **Scripting**, **Open** berkas skripnya, tekan **Run Script**.

## Memakai mesh dari Tripo3D atau aplikasi lain

Tripo3D, Meshy, atau hasil segmentasi CT bisa dipakai lewat tombol **Muat mesh .obj**:

1. Ekspor sebagai **.obj** berisi kedua paru dalam satu berkas.
2. Muat lewat tombol di bawah paru 3D.

Simulator otomatis menegakkan mesh yang diekspor dengan sumbu Z ke atas, dan menipiskan mesh
beresolusi tinggi sampai sekitar 9.000 segitiga supaya tetap lancar. Model dari AI generatif
biasanya tidak punya fisura yang benar, jadi pembagian lobus dihitung dari posisi, bukan dari
geometrinya.

## Tampilan 3D: WebGL dan cadangannya

Paru digambar dengan WebGL: cahaya per piksel, tekstur jaringan prosedural, trakea 3D bercincin.
Pojok kanan bawah panggung menunjukkan mode yang sedang dipakai. Kalau peramban tidak mendukung
WebGL, simulator otomatis beralih ke kanvas 2D; semua fitur tetap jalan, hanya tampilannya lebih
sederhana.
