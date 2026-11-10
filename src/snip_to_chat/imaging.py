"""이미지 처리: 빈 화면 판정, PNG/DIB 변환, 크기 줄이기."""

from __future__ import annotations

import base64
import io

from PIL import Image

# Claude가 이미지를 처리할 때 긴 변 기준으로 줄이는 크기와 비슷하게 맞춘다.
MCP_MAX_EDGE = 1568


def is_blank(img: Image.Image, tolerance: int = 3) -> bool:
    """캡처가 실패해서 한 가지 색으로만 채워졌는지 본다.

    '어둡다'가 아니라 '모든 픽셀이 거의 같은 색'일 때만 빈 화면으로 본다.
    다크 모드 창(대부분 검정 + 글자)은 빈 화면이 아니다.
    """
    if img.width == 0 or img.height == 0:
        return True
    sample = img.convert("RGB")
    # 큰 이미지는 줄여서 보되, 가는 글자가 사라지지 않게 NEAREST로 샘플링한다.
    if sample.width * sample.height > 800 * 800:
        scale = max(sample.width, sample.height) / 800
        sample = sample.resize(
            (max(1, int(sample.width / scale)), max(1, int(sample.height / scale))),
            Image.NEAREST,
        )
    extrema = sample.getextrema()  # ((rmin, rmax), (gmin, gmax), (bmin, bmax))
    if all(hi - lo <= tolerance for lo, hi in extrema):
        # 축소 샘플에서 균일해도 원본에 가는 선이 있을 수 있으니 원본으로 한 번 더 본다.
        full = img.convert("RGB").getextrema()
        return all(hi - lo <= tolerance for lo, hi in full)
    return False


def to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def to_dib_bytes(img: Image.Image) -> bytes:
    """클립보드 CF_DIB 형식: BMP 파일에서 14바이트 파일 헤더를 뺀 것."""
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="BMP")
    return buf.getvalue()[14:]


def downscale(img: Image.Image, max_edge: int = MCP_MAX_EDGE) -> Image.Image:
    longest = max(img.width, img.height)
    if longest <= max_edge:
        return img
    scale = max_edge / longest
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def to_mcp_image_content(img: Image.Image) -> dict:
    small = downscale(img)
    return {
        "type": "image",
        "data": base64.b64encode(to_png_bytes(small)).decode("ascii"),
        "mimeType": "image/png",
    }


def dim(img: Image.Image, factor: float = 0.55) -> Image.Image:
    """선택 화면 배경용으로 어둡게 만든다."""
    return img.convert("RGB").point(lambda v: int(v * factor))
