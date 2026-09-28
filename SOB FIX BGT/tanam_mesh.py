"""
Menanam paru_blender.obj ke dalam viva-mpc-simulator.html.

Ini Python biasa, tidak butuh Blender. Jalankan setelah buat_paru_blender.py
supaya simulator langsung memakai mesh baru saat dibuka, tanpa perlu menekan
tombol Muat mesh setiap kali.

    python tanam_mesh.py
"""
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
obj_path = HERE / "paru_blender.obj"
html_path = HERE / "viva-mpc-simulator.html"

if not obj_path.exists():
    sys.exit("paru_blender.obj belum ada. Jalankan dulu: blender -b --python buat_paru_blender.py")

lines = []
for line in obj_path.read_text().splitlines():
    if line.startswith("v "):
        q = line.split()
        lines.append("v " + " ".join(("%.3f" % float(x)).rstrip("0").rstrip(".") for x in q[1:4]))
    elif line.startswith("f "):
        lines.append("f " + " ".join(t.split("/")[0] for t in line.split()[1:]))
obj = "\n".join(lines)

html = html_path.read_text(encoding="utf-8")
new, n = re.subn(r"const LUNG_OBJ=`[\s\S]*?`;", lambda m: "const LUNG_OBJ=`" + obj + "`;", html, count=1)
if n != 1:
    sys.exit("Penanda LUNG_OBJ tidak ditemukan di simulator.")
html_path.write_text(new, encoding="utf-8")
faces = sum(1 for l in lines if l.startswith("f "))
print(f"Mesh ditanam: {faces} muka, simulator {len(new)/1024:.0f} KB")
