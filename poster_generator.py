from PIL import Image, ImageDraw, ImageFont
import pandas as pd
import qrcode
import requests
import io
import os
import json
from urllib.parse import quote
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==== 配置区域 ====
FONT_PATH = "/Users/feidabao/Library/Fonts/SourceHanSansCN-Medium.otf"
DATA_FILE = "data.xlsx"
KV_FOLDER = "kv_imgs"
OUTPUT_FOLDER = "output"
LEFT_MARGIN = 50
LINE_SPACING = 5
POSTER_WIDTH = 750
SIGN_API_PREFIX = "你的接口地址"

# ==== 1. 初始化自动重试的网络会话 ====
def create_robust_session():
    session = requests.Session()
    retry_strategy = Retry(
        total=3, 
        backoff_factor=0.5, 
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

session = create_robust_session()

# ==== 函数：自动换行绘制文字 ====
def draw_wrap_text(draw, text, font, x, y, max_width, fill="#000000"):
    current_line = ""
    current_y = y
    for char in text:
        test_line = current_line + char
        bbox = draw.textbbox((0,0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w > max_width:
            draw.text((x, current_y), current_line, font=font, fill=fill)
            current_y += font.size + LINE_SPACING
            current_line = char
        else:
            current_line = test_line
    if current_line:
        draw.text((x, current_y), current_line, font=font, fill=fill)
        current_y += font.size + LINE_SPACING
    return current_y

for folder in [KV_FOLDER, OUTPUT_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

df = pd.read_excel(DATA_FILE)
print(f"📑 读取到 {len(df)} 条数据")

# ==== 主循环生成海报 ====
for idx, row in df.iterrows():
    title = str(row['title'])
    date = str(row['date'])
    number = str(row['number'])
    link = str(row['link'])
    kv_base_url = str(row['kv_image_name'])

    # --- 步骤 1：从 API 获取所有可能的 URL ---
    try:
        encoded_param = quote(kv_base_url, safe='')
        full_sign_url = SIGN_API_PREFIX + encoded_param
        resp = session.get(full_sign_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        # 将所有备选 URL 放入列表，按优先级排序
        urls_to_try = []
        if data.get("imgurl"): urls_to_try.append(data.get("imgurl"))
        if data.get("limgurl"): urls_to_try.append(data.get("limgurl"))
        
    except Exception as e:
        print(f"❌ 签名接口获取失败: {title}，原因: {e}")
        continue

    # --- 步骤 2：尝试下载图片（带回退机制） ---
    kv_img = None
    last_error = ""
    
    for kv_url in urls_to_try:
        try:
            img_resp = session.get(kv_url, timeout=20)
            img_resp.raise_for_status()
            kv_img = Image.open(io.BytesIO(img_resp.content)).convert("RGB")
            if kv_img: break # 只要有一个成功就跳出循环
        except Exception as e:
            last_error = str(e)
            print(f"⚠️ 尝试下载失败 (将换个链接再试): {kv_url[:50]}... 原因: {e}")
            continue

    if kv_img is None:
        print(f"❌ 彻底失败: {title}。所有 URL 都无法下载。")
        print(f"   [排查建议]：后端提供的签名 URL 在 OSS 侧报 400，说明该原图无法处理。")
        continue

    # ==========================================================
    # 以下布局代码完全保持不变
    # ==========================================================
    kv_w, kv_h = kv_img.size
    new_w = POSTER_WIDTH
    new_h = int(kv_h * (new_w / kv_w))
    kv_img = kv_img.resize((new_w, new_h))

    font_title = ImageFont.truetype(FONT_PATH, 40)
    font_date = ImageFont.truetype(FONT_PATH, 24)
    font_number = ImageFont.truetype(FONT_PATH, 20)
    font_tips = ImageFont.truetype(FONT_PATH, 32)

    temp_img = Image.new("RGB", (new_w, 1000), "white")
    draw_temp = ImageDraw.Draw(temp_img)
    text_y = new_h + 35
    text_y = draw_wrap_text(draw=draw_temp, text=title, font=font_title, x=LEFT_MARGIN, y=text_y, max_width=POSTER_WIDTH - 2*LEFT_MARGIN)
    text_y = draw_wrap_text(draw=draw_temp, text=date, font=font_date, x=LEFT_MARGIN, y=text_y + 5, max_width=POSTER_WIDTH - 2*LEFT_MARGIN)
    text_y = draw_wrap_text(draw=draw_temp, text=f"直播间号:{number}", font=font_number, x=LEFT_MARGIN, y=text_y + 5, max_width=POSTER_WIDTH - 2*LEFT_MARGIN)

    qr_size = 400
    tips_height = font_tips.size
    bottom_margin = 20
    extra_bottom_space = 50

    poster_height = text_y + qr_size + tips_height + 3*LINE_SPACING + bottom_margin + extra_bottom_space

    poster = Image.new("RGB", (POSTER_WIDTH, poster_height), "white")
    poster.paste(kv_img, (0,0))
    draw = ImageDraw.Draw(poster)

    text_y = new_h + 35
    text_y = draw_wrap_text(draw=draw, text=title, font=font_title, x=LEFT_MARGIN, y=text_y, max_width=POSTER_WIDTH - 2*LEFT_MARGIN, fill="#333333")
    text_y = draw_wrap_text(draw=draw, text=date, font=font_date, x=LEFT_MARGIN, y=text_y + 5, max_width=POSTER_WIDTH - 2*LEFT_MARGIN, fill="#999999")
    text_y = draw_wrap_text(draw=draw, text=f"直播间号:{number}", font=font_number, x=LEFT_MARGIN, y=text_y + 5, max_width=POSTER_WIDTH - 2*LEFT_MARGIN, fill="#999999")

    qr = qrcode.make(link)
    qr = qr.resize((qr_size, qr_size))
    qr_y = text_y + 15
    poster.paste(qr, ((POSTER_WIDTH - qr_size)//2, qr_y))

    tips_text = "你的文案"
    bbox = draw.textbbox((0,0), tips_text, font=font_tips)
    tw = bbox[2] - bbox[0]
    draw.text(((POSTER_WIDTH - tw)//2, qr_y + qr_size + 15), tips_text, font=font_tips, fill="#999999")

    safe_title = "".join(c if c not in "/\\:*?\"<>|" else "_" for c in title)
    safe_date = "".join(c if c not in "/\\:*?\"<>|" else "_" for c in date)

    output_filename = f"{safe_title}_{safe_date}.jpg"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)
    poster.save(output_path, "JPEG")
    print(f"✅ 已成功生成: {title}")

print("\n🎉 任务结束！")
