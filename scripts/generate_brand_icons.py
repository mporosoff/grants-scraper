"""Generate raster fallbacks for the hand-authored brand SVG icons.

The SVG files remain the source used by modern browsers. These raster versions
cover messaging crawlers, Apple touch icons, legacy favicon requests, and web
app manifests that do not consistently support SVG artwork.
"""

from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ICON_DIR = ROOT / "assets" / "icons"
SOCIAL_DIR = ROOT / "assets" / "social"
CANVAS = 512


def vertical_gradient(top: str, bottom: str) -> Image.Image:
    image = Image.new("RGBA", (CANVAS, CANVAS))
    pixels = image.load()
    start = tuple(bytes.fromhex(top.removeprefix("#")))
    end = tuple(bytes.fromhex(bottom.removeprefix("#")))
    for y in range(CANVAS):
        blend = y / (CANVAS - 1)
        color = tuple(round(a + (b - a) * blend) for a, b in zip(start, end))
        for x in range(CANVAS):
            pixels[x, y] = (*color, 255)
    return image


def rounded_background(top: str, bottom: str) -> Image.Image:
    gradient = vertical_gradient(top, bottom)
    mask = Image.new("L", (CANVAS, CANVAS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 511, 511), radius=120, fill=255)
    output = Image.new("RGBA", gradient.size, (0, 0, 0, 0))
    output.paste(gradient, mask=mask)
    return output


def funding_finder_icon() -> Image.Image:
    image = rounded_background("#0066FD", "#001E5F")
    draw = ImageDraw.Draw(image)

    draw.rounded_rectangle((96, 88, 368, 400), radius=48, fill="#FFFFFF")
    for line, width in (((160, 176, 296, 176), 24), ((160, 232, 264, 232), 24), ((160, 288, 232, 288), 24)):
        draw.line(line, fill="#B7D3FF", width=width)

    draw.ellipse((240, 232, 416, 408), fill="#FFD82B", outline="#FFFFFF", width=24)
    draw.ellipse((274, 266, 382, 374), fill="#FFF3B1")
    draw.line((392, 384, 448, 440), fill="#FFD82B", width=48)
    draw.line((292, 320, 364, 320), fill="#001E5F", width=13)
    draw.line((328, 284, 328, 356), fill="#001E5F", width=13)
    return image


def faculty_pairing_icon() -> Image.Image:
    image = rounded_background("#021BC3", "#001E5F")
    draw = ImageDraw.Draw(image)

    connector = {"fill": "#FFD82B", "width": 24, "joint": "curve"}
    draw.line((168, 168, 256, 272, 352, 152), **connector)
    draw.line((176, 344, 256, 272, 352, 344), **connector)

    circles = (
        ((88, 80, 232, 224), "#B7D3FF"),
        ((288, 72, 432, 216), "#66A2FF"),
        ((96, 288, 240, 432), "#FFD82B"),
        ((288, 288, 432, 432), "#FFC200"),
    )
    for bounds, fill in circles:
        draw.ellipse(bounds, fill=fill, outline="#FFFFFF", width=20)

    draw.ellipse((200, 208, 312, 320), fill="#FFFFFF")
    draw.line((236, 252, 276, 252), fill="#0066FD", width=13)
    draw.line((236, 276, 264, 276), fill="#0066FD", width=13)
    return image


def save_icon_family(stem: str, image: Image.Image) -> None:
    for size in (32, 180, 192, 512):
        resized = image.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(ICON_DIR / f"{stem}-{size}.png", optimize=True)
    image.save(
        ICON_DIR / f"{stem}.ico",
        format="ICO",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )


def save_social_card(source_name: str, output_name: str) -> None:
    source = Image.open(SOCIAL_DIR / source_name).convert("RGB")
    if source.size != (1200, 630):
        raise ValueError(f"{source_name} must remain a wide 1200x630 card")
    source.save(
        SOCIAL_DIR / output_name,
        format="JPEG",
        quality=92,
        subsampling=0,
        optimize=True,
        progressive=False,
    )


def main() -> None:
    ICON_DIR.mkdir(parents=True, exist_ok=True)
    save_icon_family("funding-finder", funding_finder_icon())
    save_icon_family("faculty-pairing", faculty_pairing_icon())
    (ROOT / "favicon.ico").write_bytes((ICON_DIR / "funding-finder.ico").read_bytes())
    save_social_card("funding-finder-preview.jpg", "funding-finder-link-preview.jpg")
    save_social_card("faculty-pairing-preview.jpg", "faculty-pairing-link-preview.jpg")


if __name__ == "__main__":
    main()
