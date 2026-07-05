"""DALL-E 3으로 배경 이미지 생성 — 없으면 그라디언트 폴백"""
import io
import requests
from pathlib import Path
from PIL import Image

try:
    from openai import OpenAI
    _openai_available = True
except ImportError:
    _openai_available = False

from config import OPENAI_API_KEY, IMAGE_SIZE, CATEGORIES


def generate_background(dalle_prompt: str, category: str, save_path: Path) -> Path:
    """DALL-E로 배경 생성, 실패 시 그라디언트 폴백"""
    if OPENAI_API_KEY and _openai_available:
        try:
            return _dalle_background(dalle_prompt, save_path)
        except Exception as e:
            print(f"[generator] DALL-E 실패, 그라디언트 사용: {e}")

    return _gradient_background(category, save_path)


def _dalle_background(prompt: str, save_path: Path) -> Path:
    client = OpenAI(api_key=OPENAI_API_KEY)

    enhanced_prompt = (
        f"{prompt} "
        "Style: cinematic, high quality, abstract art, no text, no letters, no watermark. "
        "Aspect ratio: square 1:1."
    )

    response = client.images.generate(
        model="dall-e-3",
        prompt=enhanced_prompt,
        size="1024x1024",
        quality="standard",
        n=1,
    )

    image_url = response.data[0].url
    img_data = requests.get(image_url, timeout=30).content
    img = Image.open(io.BytesIO(img_data)).resize(IMAGE_SIZE, Image.LANCZOS)
    img.save(save_path, "PNG")
    print(f"[generator] DALL-E 이미지 저장: {save_path}")
    return save_path


def _gradient_background(category: str, save_path: Path) -> Path:
    from PIL import ImageDraw
    import math

    cat_cfg = CATEGORIES.get(category, CATEGORIES["hot"])
    bg = cat_cfg["bg_color"]
    accent = cat_cfg["color"]

    w, h = IMAGE_SIZE
    img = Image.new("RGB", IMAGE_SIZE)
    draw = ImageDraw.Draw(img)

    for y in range(h):
        t = y / h
        r = int(bg[0] + (accent[0] - bg[0]) * t * 0.4)
        g = int(bg[1] + (accent[1] - bg[1]) * t * 0.4)
        b = int(bg[2] + (accent[2] - bg[2]) * t * 0.4)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # 원형 액센트 장식
    for i in range(5):
        cx = int(w * (0.1 + i * 0.2))
        cy = int(h * 0.3)
        r_size = 80 + i * 30
        opacity = 30 - i * 5
        overlay = Image.new("RGBA", IMAGE_SIZE, (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay)
        od.ellipse(
            [cx - r_size, cy - r_size, cx + r_size, cy + r_size],
            fill=(*accent, opacity),
        )
        img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    img.save(save_path, "PNG")
    print(f"[generator] 그라디언트 배경 저장: {save_path}")
    return save_path
