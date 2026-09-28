# VIVA-MPC

Sistem otomasi ventilasi mekanis yang memperlakukan **bentuk statistik pola napas**
sebagai variabel keputusan — bukan hanya nilai reratanya.

```
u = [ VT_rerata, PEEP, RR_rerata, FiO₂, CV, γ, β ]
                                  └─ inilah kebaruannya ─┘
```

Seluruh literatur closed-loop ventilation (ASV, INTELLiVENT, SmartCare, dan gelombang
reinforcement learning terbaru) berhenti pada empat yang pertama. Ventilasi variabel
konvensional mematok tiga yang terakhir sekali di awal lalu membekukannya.

---

## Mulai dari mana

**Ingin langsung melihat hasilnya?**
Klik dua kali `viva-mpc-simulator.html`. Tidak perlu memasang apa pun, tidak perlu
server, tidak perlu koneksi internet. Tekan **▶ Demo terpandu** — seluruh argumen
sistem ini tersaji dalam empat tahap, sekitar satu menit.

Paru tiga dimensinya dimodelkan di Blender, bukan dari rumus. Sangkar rendah-poligon
ditempatkan dari proporsi anatomis tampak anterior, dihaluskan dengan subdivision
surface dua tingkat, lalu takik jantung dan cekungan hilum dipotong dengan operasi
boolean. Hasilnya di-decimate ke anggaran yang sanggup digambar kanvas dua dimensi
60 kali per detik, lalu ditanam ke dalam halaman sebagai teks OBJ — ditanam, bukan
dimuat lewat fetch, karena halaman ini harus tetap jalan dengan klik dua kali tanpa
server.

Skripnya ada: `buat_paru_blender.py`. Jalankan `blender -b --python buat_paru_blender.py`
kalau Anda mau menyetel bentuknya; semua proporsi ada di bagian atas berkas sebagai
angka yang bisa diubah. Mesh mentahnya juga disertakan sebagai `paru_blender.obj`.

Yang bisa dilakukan pada tampilan 3D:

| Aksi | Cara |
|---|---|
| Detail organ | klik bagian parunya — muncul nama lobus, nama Latin, jumlah segmen bronkopulmoner, dan status ventilasinya saat itu juga |
| Putar | seret, atau tombol panah setelah kanvas difokuskan |
| Perbesar | gulir di atas kanvas |
| Sudut baku | Anterior, Posterior, Lateral, Oblik |
| Lihat ke dalam | tombol Tembus pandang — percabangan bronkus sampai ke tiap kompartemen |

Paru kanan tiga lobus, paru kiri dua, dengan asimetri yang benar: kanan lebih pendek
dan lebar, kiri lebih tinggi dan ramping karena jantung merampas ruangnya. Fisuranya
bukan sekadar garis warna — simpul di dekat batas lobus ditarik masuk sehingga
terbentuk alur yang menangkap bayangan.

---

## Yang ada di layar

Alur kerjanya bernomor 1 sampai 5: pilih pasien, atur ventilator, atur pola napas, baca hasil,
analisis. Tiap pembacaan punya batang rentang dan vonis aman/waspada/bahaya. Kartu Analisis
menerjemahkan angka jadi kalimat biasa berisi apa yang terjadi dan apa yang bisa dilakukan, dan
setelah VIVA-MPC dijalankan ia menampilkan tabel sebelum&#8211;sesudah yang diukur otomatis.
Tanda **?** menjelaskan tiap istilah; tombol **Panduan** membuka penjelasan lengkap tentang
kegunaan, cara kerja lima lapis, langkah penggunaan, dan arti setiap pembacaan.

Paru 3D digambar dengan WebGL: cahaya per piksel, tekstur lobulus prosedural, kilau pleura,
dan trakea 3D bercincin kartilago yang bercabang ke hilum kedua paru.

## Isi folder

| Berkas | Keterangan |
|---|---|
| `viva-mpc-simulator.html` | Simulator interaktif dengan paru 3D. Berdiri sendiri. |
| `.vscode/launch.json` | Empat konfigurasi Run &amp; Debug siap pakai |
| `LAPORAN.md` | Hasil, temuan, kegagalan, dan langkah berikutnya |
| `CARA_MENJALANKAN.md` | Panduan VS Code langkah demi langkah |
| `cek_instalasi.py` | Verifikasi cepat semua komponen sebelum eksperimen panjang |
| `vivampc/` | Paket Python: twin, estimator, surrogate, controller, baseline |
| `run_experiments.py` | Matriks enam skenario × empat controller |
| `run_pareto.py` | Ablasi variabilitas |
| `make_figures.py` | Menghasilkan tiga gambar |
| `uji_web.js` | Uji runtime simulator dengan jsdom (opsional, butuh Node) |
| `gambar*.png`, `*.json` | Hasil yang sudah jadi, siap dipakai |

---

## Arsitektur

```
Lapis 0  sensing          flow, Paw, EtCO₂, SpO₂, EIT
Lapis 1  estimator        Moving Horizon Estimation untuk R, E₁, E₂
Lapis 2  digital twin     20 kompartemen, rekrutmen bergantung waktu
Lapis 3  MPC              economic stochastic, horizon 45 napas
Lapis 4  safety           hierarki keras: ventilasi → oksigenasi → tekanan
```

Twin fidelitas tinggi berperan sebagai pasien; controller memakai model tingkat-napas
yang jauh lebih kasar. Ketidakcocokan antara keduanya disengaja — itulah ujian
kekukuhan yang sesungguhnya.

---

## Temuan utama

Controller memilih dosis variabilitas yang berbeda-beda menurut kondisi paru:
0,22 pada ARDS ringan, 0,19 pada sedang, tetapi hanya 0,02 pada paru obstruktif.
Ia menolak variabilitas justru di kondisi yang tidak punya unit kolaps untuk direkrut.

Mematok CV 30% tanpa memandang kondisi — praktik yang dipakai seluruh literatur
ventilasi variabel — menaikkan mechanical power 1,7 sampai 2,7 kali.

Ablasinya belum mendukung klaim superioritas. Penyebabnya sudah dilacak sampai ke
kalibrasi surrogate. Rinciannya di `LAPORAN.md` bagian 4.

---

## Catatan kejujuran

Semua angka berasal dari simulasi terhadap model yang ditulis sendiri. Twin-nya
dirancang konsisten dengan arah temuan literatur, tetapi ia bukan pasien dan belum
pernah dikalibrasi terhadap data manusia. Ini alat berpikir, bukan alat klinis.
