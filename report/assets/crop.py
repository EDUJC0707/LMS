from PIL import Image
def crop(src, box, out):
    Image.open(src).convert("RGBA").crop(box).save(out)
    print(out, Image.open(out).size)
crop("shot-vdocipher.png", (95, 30, 610, 175), "logo-vdocipher.png")
crop("shot-mux.png", (150, 45, 360, 180), "logo-mux.png")
crop("shot-channeltalk.png", (128, 35, 470, 150), "logo-channel.png")
crop("shot-channeltalk.png", (150, 940, 2600, 1780), "fig-channel.png")
crop("shot-vdocipher.png", (560, 250, 2320, 990), "fig-vdocipher.png")
