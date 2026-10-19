"""앱 아이콘 다시 그리기: python assets/make_icon.py assets/app.ico 미리보기.png"""
import sys
from PIL import Image, ImageDraw, ImageFont
out, png = sys.argv[1], sys.argv[2]
S = 1024
im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(im)
red = (214, 48, 49, 255)
# 종이: 오른쪽 위 모서리가 접힌 흰 장
m, fold = 120, 230
x0, y0, x1, y1 = m + 40, m - 20, S - m - 40, S - m + 20
shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0)); sd = ImageDraw.Draw(shadow)
sd.polygon([(x0 + 18, y0 + 26), (x1 - fold + 18, y0 + 26), (x1 + 18, y0 + fold + 26), (x1 + 18, y1 + 26), (x0 + 18, y1 + 26)], fill=(0, 0, 0, 70))
im = Image.alpha_composite(im, shadow); d = ImageDraw.Draw(im)
d.polygon([(x0, y0), (x1 - fold, y0), (x1, y0 + fold), (x1, y1), (x0, y1)], fill=(255, 255, 255, 255), outline=(200, 200, 200, 255), width=10)
d.polygon([(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)], fill=(235, 235, 235, 255), outline=(200, 200, 200, 255), width=10)
# 아래 빨간 띠에 PDF, 가운데 큰 R
band = (x0 - 70, y1 - 300, x1 - 120, y1 - 90)
d.rounded_rectangle(band, radius=40, fill=red)
fb = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 150)
cx = (band[0] + band[2]) / 2; cy = (band[1] + band[3]) / 2
d.text((cx, cy), "PDF", font=fb, fill="white", anchor="mm")
fr = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 520)
d.text(((x0 + x1) / 2 - 10, y0 + 330), "R", font=fr, fill=red, anchor="mm")
im.save(png)
im.save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
