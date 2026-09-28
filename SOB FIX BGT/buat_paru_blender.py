"""
Membangun mesh paru di Blender, lalu mengekspornya sebagai OBJ untuk simulator.

Kenapa lewat Blender dan bukan rumus di JavaScript seperti sebelumnya:

  * Subdivision surface Catmull-Clark menghaluskan sangkar rendah-poligon menjadi
    permukaan mulus. Faceting yang selama ini terlihat hilang, dan yang lebih
    penting, saya cukup menaruh sedikit simpul di tempat yang benar secara
    anatomis alih-alih mencari rumus yang kebetulan menghasilkan bentuk itu.
  * Operasi boolean memberi takik jantung dan cekungan hilum sebagai potongan
    sungguhan, bukan sebagai pergeseran simpul yang gampang melipat sendiri.
  * Hasilnya OBJ biasa, jadi simulator memuatnya lewat jalur adoptMesh yang
    sudah ada. Fisika, pewarnaan rekrutmen, dan pemilihan lobus tidak berubah.

Proporsi diambil dari tampak anterior: paru jauh lebih lebar dibanding tinggi
daripada yang saya buat sebelumnya, batas superiornya melandai ke lateral, dan
titik terendahnya ada di sudut kostofrenikus, jauh di lateral.

Jalankan:  blender -b --python buat_paru_blender.py
"""

import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

# Hasil ditulis di samping skrip ini, bukan ke /tmp. Folder /tmp tidak ada di
# Windows, dan Blender akan gagal menulis tanpa pesan yang jelas.
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.environ.get("LUNG_OBJ", os.path.join(HERE, "paru_blender.obj"))

NLOOP = 13          # cincin penampang pada sangkar
NRAD = 18           # titik mengelilingi tiap cincin
DISSOLVE_DEG = 1.0  # sudut ambang peleburan muka sebidang
SUBSURF = 1         # kehalusan datang dari tingkat subdivisi, bukan dari
                    # kerapatan sangkar: sangkar jarang + subdivisi dua tingkat
                    # jauh lebih mulus daripada sangkar rapat + satu tingkat,
                    # pada jumlah poligon akhir yang kurang lebih sama.

# Setengah-lebar dan kedalaman terhadap tinggi, dari apeks (t=0) ke basis (t=1).
HALF = [0.36, 0.60, 0.76, 0.87, 0.93, 0.97, 1.00, 1.00, 0.96, 0.66]
DEEP = [0.40, 0.62, 0.76, 0.86, 0.92, 0.97, 1.00, 1.00, 0.94, 0.64]

W = 0.50            # skala setengah-lebar (lebar penuh = 2W)
D = 0.52            # skala kedalaman anteroposterior
H = 2.30            # tinggi paru
MID = 0.10          # jarak permukaan mediastinal dari garis tengah

# Paru kanan lebih pendek dan lebar; paru kiri lebih tinggi dan ramping karena
# jantung merampas ruangnya.
# Paru kanan memang sedikit lebih besar dan lebih pendek karena hati mendesaknya
# dari bawah; paru kiri lebih tinggi dan ramping karena jantung merampas ruangnya.
# Selisihnya sekitar sepersepuluh, bukan seperenam -- angka lama membuat yang satu
# tampak jelas lebih besar dan itu langsung terbaca sebagai cacat, bukan anatomi.
SIDE = {1: dict(h=0.975, w=1.030, d=1.015), -1: dict(h=1.025, w=0.955, d=0.990)}

OBLIQ_Z = {1: -0.16, -1: -0.10}   # tinggi bidang fisura oblik tiap paru

SUP_SLOPE = 0.30    # batas superior melandai ke lateral
INF_SLOPE = 0.34    # titik terendah di sudut kostofrenikus


def lerp_list(arr, t):
    n = len(arr) - 1
    x = min(0.99999, max(0.0, t)) * n
    i = int(x)
    f = x - i
    a, b = arr[i], arr[min(n, i + 1)]
    return a + (b - a) * f


def build_cage(side):
    g = SIDE[side]
    bm = bmesh.new()
    rings = []

    for iv in range(NLOOP):
        t = iv / (NLOOP - 1)
        half = W * lerp_list(HALF, t) * g["w"]
        dep = D * lerp_list(DEEP, t) * g["d"]
        cx = MID + half
        y0 = 1.15 - H * t * g["h"]

        ring = []
        for iu in range(NRAD):
            th = 2 * math.pi * iu / NRAD
            cs, sn = math.cos(th), math.sin(th)

            # Permukaan mediastinal dipipihkan dengan mengurangi kedalamannya.
            med = 0.5 * (1 - cs)
            flat = 1 - 0.40 * (med ** 1.8)

            x = side * (cx + half * cs)
            z = dep * sn * flat * (1 + 0.14 * sn)
            y = y0

            # Batas superior melandai ke lateral, batas inferior lebih jauh lagi.
            lat = 0.5 + 0.5 * cs
            if t < 0.30:
                f = 1 - t / 0.30
                y -= SUP_SLOPE * f * f * lat
            if t > 0.78:
                f = (t - 0.78) / 0.22
                y -= INF_SLOPE * f * f * lat

            ring.append(bm.verts.new(Vector((x, z, y))))
        rings.append(ring)

    bm.verts.ensure_lookup_table()
    for a, b in zip(rings, rings[1:]):
        for i in range(NRAD):
            j = (i + 1) % NRAD
            bm.faces.new((a[i], a[j], b[j], b[i]))

    # Tutup apeks dan basis dengan n-gon; subdivision membulatkannya sendiri.
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])

    bm.normal_update()
    mesh = bpy.data.meshes.new(f"paru_{side}")
    bm.to_mesh(mesh)
    bm.free()

    obj = bpy.data.objects.new(f"paru_{side}", mesh)
    bpy.context.collection.objects.link(obj)
    return obj


def carve(target, name, loc, scale, rot=(0, 0, 0)):
    """Potong cekungan memakai bola yang diubah bentuk."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=16, location=loc)
    cut = bpy.context.active_object
    cut.name = name
    cut.scale = scale
    cut.rotation_euler = rot
    _apply_bool(target, cut)


def slice_fissure(target, name, loc, rot, scale, thickness=0.020):
    """
    Iris fisura dengan bilah tipis sampai tembus.

    Ini beda mendasar dari menggambar garis gelap di permukaan. Boolean difference
    dengan bilah padat menghasilkan cangkang-cangkang tertutup yang benar-benar
    terpisah, lengkap dengan tutup pada bidang irisnya. Artinya lobus punya celah
    nyata yang menangkap bayangan dari sudut mana pun, dan siluetnya pun ikut
    terbelah -- hal yang tidak pernah bisa ditiru garis dua dimensi.
    """
    bpy.ops.mesh.primitive_cube_add(size=2, location=loc)
    blade = bpy.context.active_object
    blade.name = name
    blade.scale = (scale[0], scale[1], thickness)
    blade.rotation_euler = rot
    _apply_bool(target, blade)


def _apply_bool(target, cut):
    mod = target.modifiers.new("carve", "BOOLEAN")
    mod.object = cut
    mod.operation = "DIFFERENCE"
    mod.solver = "EXACT"

    bpy.context.view_layer.objects.active = target
    bpy.ops.object.modifier_apply(modifier=mod.name)
    bpy.data.objects.remove(cut, do_unlink=True)


def main():
    bpy.ops.wm.read_factory_settings(use_empty=True)

    objs = []
    for side in (1, -1):
        o = build_cage(side)

        sub = o.modifiers.new("sub", "SUBSURF")
        sub.levels = SUBSURF
        sub.render_levels = SUBSURF
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=sub.name)

        # SEMUA boolean dikerjakan setelah subdivisi.
        #
        # Versi sebelumnya memotong hilum dan takik jantung pada sangkar kasar
        # dulu. Hasilnya sangkar jadi tidak rapi, subdivision menyebarkan
        # ketidakrapian itu, dan boolean fisura berikutnya gagal di atasnya --
        # pada paru kiri seluruh lobus superior ikut terbuang tanpa pesan galat.
        carve(o, f"hilum{side}", (side * 0.05, 0.03, 0.22), (0.16, 0.22, 0.26))
        if side == -1:
            carve(o, "notch", (-MID - 0.04, -0.30, -0.22), (0.24, 0.30, 0.44))

        # Fisura diiris setelah subdivisi. Kalau diiris sebelum, subdivision
        # membulatkan tepi irisan dan celahnya menutup kembali.
        #
        # Fisura oblik berjalan miring: tinggi di posterior, turun jauh ke anterior.
        # Bidangnya dimiringkan 42 derajat terhadap bidang datar, persis arah yang
        # dipakai ahli anatomi menjelaskannya sebagai garis dari vertebra torakal
        # ketiga menuju kartilago kosta keenam.
        slice_fissure(o, f"oblik{side}", (side * 0.55, 0.0, OBLIQ_Z[side]),
                      (math.radians(42), 0, 0), (1.5, 1.7))

        if side == 1:
            # Fisura horizontal hanya ada pada paru kanan, mendatar, dan hanya
            # menjangkau bagian anterior sampai bertemu fisura oblik.
            slice_fissure(o, "horizontal", (0.55, -0.62, 0.30),
                          (0, 0, 0), (1.5, 0.72))

        # Jumlah muka dikendalikan dari kerapatan sangkar, BUKAN dari decimate.
        #
        # Decimate collapse memang menurunkan jumlah muka, tetapi ia menghasilkan
        # segitiga yang panjang dan tidak beraturan. Normal simpul yang dirata-rata
        # dari segitiga seperti itu jadi tidak konsisten, dan permukaan yang tadinya
        # mulus berubah bersegi-segi -- persis kerusakan yang ingin dihindari.

        # Penipisan memakai DISSOLVE, bukan COLLAPSE.
        #
        # Collapse menggabungkan simpul dan menghasilkan segitiga panjang tak
        # beraturan; normal yang dirata-rata darinya jadi kacau dan permukaan
        # mulus berubah bersegi. Dissolve hanya melebur muka yang sudah hampir
        # sebidang, jadi siluet, alur fisura, dan kehalusannya tetap utuh --
        # yang hilang cuma muka yang memang tidak menyumbang bentuk apa pun.
        dis = o.modifiers.new("dis", "DECIMATE")
        dis.decimate_type = "DISSOLVE"
        dis.angle_limit = math.radians(DISSOLVE_DEG)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=dis.name)

        bpy.ops.object.shade_smooth()
        objs.append(o)

    for o in bpy.context.scene.objects:
        o.select_set(o in objs)
    bpy.context.view_layer.objects.active = objs[0]

    bpy.ops.wm.obj_export(
        filepath=OUT, export_selected_objects=True, export_materials=False,
        export_normals=False, export_uv=False, export_triangulated_mesh=False,
        forward_axis="NEGATIVE_Z", up_axis="Y",
    )

    total = sum(len(o.data.polygons) for o in objs)
    print(f"HASIL {OUT} verts={sum(len(o.data.vertices) for o in objs)} faces={total}")


main()
