import base64
import io
import struct

from PIL import Image, ImageDraw

from snip_to_chat.imaging import downscale, is_blank, to_dib_bytes, to_mcp_image_content


def test_all_black_is_blank():
    assert is_blank(Image.new("RGB", (1920, 1080), (0, 0, 0)))


def test_uniform_white_is_blank():
    assert is_blank(Image.new("RGB", (300, 200), (255, 255, 255)))


def test_dark_mode_window_is_not_blank():
    # 다크 모드 창: 거의 검정 바탕에 회색 글자. '어둡다'고 빈 화면으로 보면 안 된다
    img = Image.new("RGB", (1600, 900), (18, 18, 18))
    d = ImageDraw.Draw(img)
    for y in range(100, 800, 40):
        d.text((50, y), "dark mode text line", fill=(200, 200, 200))
    assert not is_blank(img)


def test_one_pixel_line_on_huge_image_not_blank():
    # 크게 줄여서 보면 사라지는 1px 선도 놓치지 않아야 한다
    img = Image.new("RGB", (3840, 2160), (0, 0, 0))
    ImageDraw.Draw(img).line([(0, 1001), (3839, 1001)], fill=(255, 255, 255))
    assert not is_blank(img)


def test_zero_size_is_blank():
    assert is_blank(Image.new("RGB", (0, 0)))


def test_dib_header():
    img = Image.new("RGB", (33, 7), (10, 20, 30))  # 너비 33: 행 패딩이 생기는 크기
    dib = to_dib_bytes(img)
    bi_size, width, height, planes, bitcount = struct.unpack_from("<IiiHH", dib, 0)
    assert bi_size == 40 and width == 33 and height == 7 and planes == 1 and bitcount == 24
    row = (33 * 3 + 3) & ~3
    assert len(dib) >= 40 + row * 7


def test_downscale_keeps_aspect_and_small_images():
    small = Image.new("RGB", (800, 600))
    assert downscale(small) is small
    big = downscale(Image.new("RGB", (4000, 1000)))
    assert max(big.size) == 1568 and abs(big.width / big.height - 4.0) < 0.02


def test_mcp_image_content_is_valid_png():
    c = to_mcp_image_content(Image.new("RGB", (3000, 2000), (1, 2, 3)))
    assert c["type"] == "image" and c["mimeType"] == "image/png"
    img = Image.open(io.BytesIO(base64.b64decode(c["data"])))
    assert img.format == "PNG" and max(img.size) == 1568
