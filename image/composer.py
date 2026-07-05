"""Pillow로 카드뉴스 최종 이미지 합성"""
from pathlib import Path
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import IMAGE_SIZE, CATEGORIES, BRAND_NAME, WINDOWS_FONT_PATH, WINDOWS_FONT_REGULAR


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = WINDOWS_FONT_PATH if bold else WINDOWS_FONT_REGULAR
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = list(text)
    lines = []
    current = ""
    for ch in words:
        test = current + ch
        bbox = font.getbbox(test)
        if bbox[2] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def compose_card(
    bg_path: Path,
    category: str,
    headline: str,
    summary: str,
    source: str,
    extra_text: str = "",
    output_path: Path = None,
) -> Path:
    cat = CATEGORIES[category]
    w, h = IMAGE_SIZE

    bg = Image.open(bg_path).resize(IMAGE_SIZE, Image.LANCZOS)
    bg = bg.filter(ImageFilter.GaussianBlur(radius=8))

    overlay = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    draw_ov.rectangle([0, 0, w, h], fill=(10, 10, 20, 200))
    card = Image.alpha_composite(bg.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(card)

    # 상단 카테고리 바
    bar_h = 80
    draw.rectangle([0, 0, w, bar_h], fill=(*cat["color"], 255))
    cat_font = _load_font(32, bold=True)
    draw.text((40, 22), cat["label"], font=cat_font, fill=(255, 255, 255))

    # 브랜드 + 날짜 (우상단)
    brand_font = _load_font(24, bold=False)
    date_str = datetime.now().strftime("%Y.%m.%d")
    brand_text = f"{BRAND_NAME}  |  {date_str}"
    bbox = brand_font.getbbox(brand_text)
    draw.text(
        (w - bbox[2] - 40, 26),
        brand_text,
        font=brand_font,
        fill=(255, 255, 255, 180),
    )

    # 헤드라인
    headline_font = _load_font(68, bold=True)
    margin = 60
    max_text_w = w - margin * 2
    lines = _wrap_text(headline, headline_font, max_text_w)

    summary_font = _load_font(36, bold=False)
    sum_preview = _wrap_text(summary, summary_font, max_text_w)
    total_h = len(lines[:3]) * 82 + 30 + len(sum_preview[:5]) * 50 + (88 if extra_text else 0)
    y_start = max(130, (h - total_h) // 2 - 20)

    line_h = 82
    for i, line in enumerate(lines[:3]):
        draw.text((margin, y_start + i * line_h), line, font=headline_font, fill=(255, 255, 255))

    # 헤드라인 하단 구분선
    sep_y = y_start + len(lines[:3]) * line_h + 20
    draw.rectangle([margin, sep_y, margin + 80, sep_y + 5], fill=cat["accent"])

    # 요약 텍스트
    sum_lines = _wrap_text(summary, summary_font, max_text_w)
    sum_y = sep_y + 36
    for i, line in enumerate(sum_lines[:5]):
        draw.text((margin, sum_y + i * 50), line, font=summary_font, fill=(215, 215, 215))

    # 댄스컬 소재 (social 카드에만)
    if extra_text and category == "social":
        extra_font = _load_font(30, bold=True)
        ex_label = f"댄스컬 소재라면?  {extra_text}"
        ex_lines = _wrap_text(ex_label, extra_font, max_text_w)
        ex_y = sum_y + len(sum_lines[:5]) * 50 + 36
        box_h = len(ex_lines[:2]) * 44 + 24
        draw.rectangle([margin - 10, ex_y - 12, w - margin + 10, ex_y + box_h], fill=(*cat["color"], 60))
        for i, line in enumerate(ex_lines[:2]):
            draw.text(
                (margin, ex_y + i * 44),
                line,
                font=extra_font,
                fill=(255, 255, 255),
            )

    # 하단 출처 바
    footer_h = 60
    footer_y = h - footer_h
    draw.rectangle([0, footer_y, w, h], fill=(0, 0, 0, 140))
    footer_font = _load_font(26, bold=False)
    draw.text(
        (margin, footer_y + 16),
        f"출처: {source}",
        font=footer_font,
        fill=(180, 180, 180),
    )

    if output_path is None:
        output_path = Path(f"output/{category}_{datetime.now().strftime('%Y%m%d')}.png")

    output_path.parent.mkdir(exist_ok=True)
    card.save(str(output_path), "PNG")
    print(f"[composer] 카드 저장: {output_path}")
    return output_path


def compose_cover(output_path: Path = None) -> Path:
    """커버 슬라이드 (캐러셀 첫 번째 장)"""
    w, h = IMAGE_SIZE
    card = Image.new("RGB", IMAGE_SIZE, (15, 12, 30))
    draw = ImageDraw.Draw(card)

    # 그라디언트 배경
    for y in range(h):
        t = y / h
        r = int(15 + 20 * t)
        g = int(12 + 8 * t)
        b = int(30 + 40 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # 장식 원
    for i, (cx, cy, r_size, color) in enumerate([
        (900, 200, 300, (220, 50, 50, 40)),
        (200, 800, 250, (37, 99, 235, 35)),
        (800, 900, 200, (124, 58, 237, 30)),
    ]):
        ov = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        od = ImageDraw.Draw(ov)
        od.ellipse([cx - r_size, cy - r_size, cx + r_size, cy + r_size], fill=color)
        card = Image.alpha_composite(card.convert("RGBA"), ov).convert("RGB")
        draw = ImageDraw.Draw(card)

    date_str = datetime.now().strftime("%Y년 %m월 %d일")
    day_names = ["월", "화", "수", "목", "금", "토", "일"]
    day = day_names[datetime.now().weekday()]
    date_full = f"{date_str} ({day})"

    date_font = _load_font(36, bold=False)
    draw.text((w // 2 - 200, 280), date_full, font=date_font, fill=(180, 180, 180))

    title_font = _load_font(88, bold=True)
    draw.text((w // 2 - 280, 360), "오늘의", font=title_font, fill=(255, 255, 255))
    draw.text((w // 2 - 280, 460), "카드뉴스", font=title_font, fill=(255, 255, 255))

    sub_font = _load_font(38, bold=False)
    draw.text((w // 2 - 280, 580), "HOT 핫뉴스   ECO 경제·IT   SOC 사회", font=sub_font, fill=(160, 160, 200))

    line_y = 640
    draw.rectangle([w // 2 - 280, line_y, w // 2 + 280, line_y + 4], fill=(220, 50, 50))

    brand_font = _load_font(32, bold=True)
    draw.text((w // 2 - 100, 680), BRAND_NAME, font=brand_font, fill=(200, 200, 220))

    if output_path is None:
        output_path = Path(f"output/cover_{datetime.now().strftime('%Y%m%d')}.png")

    output_path.parent.mkdir(exist_ok=True)
    card.save(str(output_path), "PNG")
    print(f"[composer] 커버 저장: {output_path}")
    return output_path
