"""Compose the website's AI / phone images (docs/img/assistant.jpg, phone-ai.jpg, phone.jpg).

    GP_SHOTS_PRIVATE=1 QT_SCALE_FACTOR=2 QT_QPA_PLATFORM=offscreen python tools/shots.py shots2x
    (phone shots: run the app on a test profile, then node tools/phone_shots.js PORT shots/phone docs/img/screen-demo.jpg)
    python tools/website_images_ai.py
"""
from PIL import Image, ImageDraw, ImageFilter

S = "shots/phone/"


def backdrop(W, H):
    im = Image.new("RGB", (W, H), (10, 12, 22))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    for cx, cy, r, col in ((0.15, 0.1, 0.5, (64, 232, 208)), (0.9, 0.3, 0.45, (139, 108, 255)),
                           (0.5, 1.1, 0.55, (255, 166, 77))):
        d.ellipse([W * cx - W * r, H * cy - W * r, W * cx + W * r, H * cy + W * r], fill=tuple(int(c * .22) for c in col))
    glow = glow.filter(ImageFilter.GaussianBlur(W // 10))
    return Image.composite(glow, im, Image.new("L", (W, H), 255)).point(lambda v: v + 10)


def rounded(img, r):
    m = Image.new("L", img.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, *img.size], r, fill=255)
    img = img.convert("RGBA")
    img.putalpha(m)
    return img


def shadow_paste(base, img, xy, r=28, blur=40):
    sh = Image.new("RGBA", (img.width + blur * 4, img.height + blur * 4), (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([blur * 2, blur * 2 + 20, blur * 2 + img.width, blur * 2 + img.height + 20],
                                         r, fill=(0, 0, 0, 170))
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)), (xy[0] - blur * 2, xy[1] - blur * 2))
    base.alpha_composite(rounded(img, r), xy)


p = Image.open(S + "phone_remote.png").convert("RGB")
p.resize((600, int(p.height * 600 / p.width)), Image.LANCZOS).save("docs/img/phone.jpg", quality=88)

W, H = 1700, 1250
base = backdrop(W, H).convert("RGBA")
a, b = Image.open(S + "phone_screen.png"), Image.open(S + "phone_ai.png")
sc = 1080 / a.height
a = a.resize((int(a.width * sc), 1080), Image.LANCZOS)
b = b.resize(a.size, Image.LANCZOS)
x0 = (W - 2 * a.width - 90) // 2
shadow_paste(base, a, (x0, (H - a.height) // 2), 48)
shadow_paste(base, b, (x0 + a.width + 90, (H - a.height) // 2), 48)
base.convert("RGB").save("docs/img/phone-ai.jpg", quality=86)

W, H = 2400, 1400
base = Image.new("RGBA", (W, H))
scr = Image.open("docs/img/screen-demo.jpg").convert("RGBA").resize((W, W * 800 // 1280), Image.LANCZOS)
base.alpha_composite(scr.crop((0, 0, W, H)))
win = Image.open("shots2x/10_assistant.png").convert("RGBA")
win = win.resize((int(win.width * 1180 / win.height), 1180), Image.LANCZOS)
shadow_paste(base, win, (W - win.width - 90, (H - win.height) // 2), 26, 50)
base.convert("RGB").save("docs/img/assistant.jpg", quality=86)
print("saved docs/img/phone.jpg, phone-ai.jpg, assistant.jpg")
