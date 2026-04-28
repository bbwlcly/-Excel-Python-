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
LOGO_PATH = "logo.png"  # 确保 logo.png 在同级目录下
DATA_FILE = "data.xlsx"
OUTPUT_FOLDER = "output"
LEFT_MARGIN = 50
LINE_SPACING = 12 
POSTER_WIDTH = 750
SIGN_API_PREFIX = "你的接口"

# --- 严耕避头尾规则 ---
# 行首禁止：这些字符绝对不能出现在开头
START_PUNCTUATION = (',', '.', '!', '?', ':', ';', '"', "'", ')', ']', '}', '>', 
                     '，', '。', '！', '？', '：', '；', '”', '’', '）', '］', '｝', 
                     '〉', '》', '」', '』', '】', '〕', '〗', '］', '、', '组', '级')
# 行末禁止：这些字符（如左括号）绝对不能出现在末尾
END_PUNCTUATION = ('(', '[', '{', '<', '（', '［', '｛', '〈', '《', '「', '『', '【', '〔', '〖', '“', '‘')

# ==== 1. 网络请求会话 (保持稳定性) ====
def create_robust_session():
    session = requests.Session()
    retry_strategy = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter); session.mount("https://", adapter)
    return session

session = create_robust_session()

# ==== 2. 核心排版引擎：物理适配 + 强制回溯校准 ====
def draw_wrap_text(draw, text, font, x, y, max_width, fill="#000000", is_justified=True):
    lines = []
    chars = list(text)
    
    while chars:
        line = ""
        # A. 寻找物理上能放下的最大字数
        while chars:
            test_line = line + chars[0]
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if (bbox[2] - bbox[0]) <= max_width:
                line += chars.pop(0)
            else:
                break
        
        # B. 强制回溯逻辑：修复避头避尾互相冲突的问题 (核心修改区域)
        if chars:
            while True:
                needs_adjust = False
                
                # 1. 避头：若下行开头是逗号/顿号/“组”等，从本行末尾挪一个字过去
                if chars and chars[0] in START_PUNCTUATION and len(line) > 1:
                    chars.insert(0, line[-1])
                    line = line[:-1]
                    needs_adjust = True
                
                # 2. 避尾：若行末是开括号等，强行踢到下一行
                if line and line[-1] in END_PUNCTUATION and len(line) > 1:
                    chars.insert(0, line[-1])
                    line = line[:-1]
                    needs_adjust = True
                    
                # 如果这一轮循环没有任何调整，说明头尾都已经合法，跳出循环
                if not needs_adjust:
                    break
        
        if line: lines.append(line)
        elif chars: lines.append(chars.pop(0)) # 保底逻辑

    # --- 绘制并实现两端对齐 ---
    current_y = y
    for i, line in enumerate(lines):
        is_last_line = (i == len(lines) - 1)
        if is_justified and not is_last_line and len(line) > 1:
            line_w = draw.textbbox((0, 0), line, font=font)[2]
            char_spacing = (max_width - line_w) / (len(line) - 1)
            temp_x = x
            for c in line:
                draw.text((temp_x, current_y), c, font=font, fill=fill)
                temp_x += draw.textbbox((0, 0), c, font=font)[2] + char_spacing
        else:
            draw.text((x, current_y), line, font=font, fill=fill)
        current_y += font.size + LINE_SPACING
    return current_y

# ==== 3. 主循环逻辑 ====
if not os.path.exists(OUTPUT_FOLDER): os.makedirs(OUTPUT_FOLDER)
df = pd.read_excel(DATA_FILE)
print(f"📑 正在为 Hotu 品牌生成精排版海报...")

for idx, row in df.iterrows():
    title, date, number, link, kv_base_url = [str(row[k]) for k in ['title', 'date', 'number', 'link', 'kv_image_name']]

    # --- 具备回退机制的图片下载 ---
    try:
        encoded_param = quote(kv_base_url, safe='')
        resp = session.get(SIGN_API_PREFIX + encoded_param, timeout=10).json()
        urls = [u for u in [resp.get("imgurl"), resp.get("limgurl")] if u]
        kv_img = None
        for url in urls:
            try:
                ir = session.get(url, timeout=20)
                kv_img = Image.open(io.BytesIO(ir.content)).convert("RGB")
                if kv_img: break
            except: continue
        if not kv_img: continue
    except: continue

    # --- 海报合成逻辑 ---
    kv_w, kv_h = kv_img.size
    new_h = int(kv_h * (POSTER_WIDTH / kv_w))
    kv_img = kv_img.resize((POSTER_WIDTH, new_h))
    
    font_title, font_date, font_number, font_tips = [ImageFont.truetype(FONT_PATH, s) for s in [40, 24, 20, 32]]

    # 预计算整体高度
    temp_img = Image.new("RGB", (POSTER_WIDTH, 2000), "white")
    draw_temp = ImageDraw.Draw(temp_img)
    ty = new_h + 35
    ty = draw_wrap_text(draw_temp, title, font_title, LEFT_MARGIN, ty, POSTER_WIDTH - 2*LEFT_MARGIN)
    ty = draw_wrap_text(draw_temp, date, font_date, LEFT_MARGIN, ty + 5, POSTER_WIDTH - 2*LEFT_MARGIN)
    ty = draw_wrap_text(draw_temp, f"直播间号:{number}", font_number, LEFT_MARGIN, ty + 5, POSTER_WIDTH - 2*LEFT_MARGIN)

    poster = Image.new("RGB", (POSTER_WIDTH, int(ty + 550)), "white")
    poster.paste(kv_img, (0,0))
    draw = ImageDraw.Draw(poster)

    # 正式绘制文字 (启用两端对齐)
    ty = new_h + 35
    ty = draw_wrap_text(draw, title, font_title, LEFT_MARGIN, ty, POSTER_WIDTH - 2*LEFT_MARGIN, fill="#333333")
    ty = draw_wrap_text(draw, date, font_date, LEFT_MARGIN, ty + 5, POSTER_WIDTH - 2*LEFT_MARGIN, fill="#999999")
    ty = draw_wrap_text(draw, f"直播间号:{number}", font_number, LEFT_MARGIN, ty + 5, POSTER_WIDTH - 2*LEFT_MARGIN, fill="#999999")

    # --- 生成带 Logo 的高纠错二维码 ---
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=2)
    qr.add_data(link)
    qr_img = qr.make_image().convert('RGB').resize((400, 400), Image.LANCZOS)
    if os.path.exists(LOGO_PATH):
        icon = Image.open(LOGO_PATH).convert("RGBA")
        sz = 400 // 5
        icon = icon.resize((sz, sz), Image.LANCZOS)
        qr_img.paste(icon, ((400 - sz) // 2, (400 - sz) // 2), icon)

    poster.paste(qr_img, ((POSTER_WIDTH - 400)//2, int(ty + 20)))
    tw = draw.textbbox((0,0), "扫码观看好图直播", font=font_tips)[2]
    draw.text(((POSTER_WIDTH - tw)//2, ty + 440), "扫码观看好图直播", font=font_tips, fill="#999999")

    # 保存文件
    safe_t = "".join(c if c not in "/\\:*?\"<>|" else "_" for c in title)
    poster.save(os.path.join(OUTPUT_FOLDER, f"{safe_t}_{idx}.jpg"), "JPEG", quality=95)
    print(f"✅ 排版优化成功: {title}")

print("\n🎉 海报已生成。")
