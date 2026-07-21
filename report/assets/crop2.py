from PIL import Image
def crop(src, box, out):
    Image.open(src).convert("RGBA").crop(box).save(out); print(out, Image.open(out).size)
crop("shot-vdocipher.png", (95, 40, 470, 140), "logo-vdocipher.png")
crop("shot-mux.png", (150, 55, 350, 170), "logo-mux.png")
crop("shot-channeltalk.png", (128, 45, 455, 140), "logo-channel.png")
