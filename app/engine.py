"""PDF overlay stamping, with no permanent storage of documents or seal images."""
from __future__ import annotations

from io import BytesIO
from math import ceil
from typing import Any
import re

from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError
from pypdf import PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

POINTS_PER_MM = 72.0 / 25.4
MAX_PAGES = 500
MAX_STAMPS = 12


class DocumentError(ValueError):
    pass


def read_pdf(data: bytes, password: str = "") -> PdfReader:
    if not data.startswith(b"%PDF-") and b"%PDF-" not in data[:1024]:
        raise DocumentError("不是有效的 PDF 文件。")
    try:
        reader = PdfReader(BytesIO(data), strict=False)
        if reader.is_encrypted:
            if not password or not reader.decrypt(password):
                raise DocumentError("PDF 已加密，请填写正确的原文件密码。")
        if not 1 <= len(reader.pages) <= MAX_PAGES:
            raise DocumentError(f"PDF 页数必须在 1–{MAX_PAGES} 页以内。")
        return reader
    except DocumentError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, IndexError) as exc:
        raise DocumentError(f"无法读取 PDF：{str(exc)[:140]}") from exc


def has_signatures(reader: PdfReader) -> bool:
    try:
        root = reader.trailer['/Root']
        if '/Perms' in root and '/DocMDP' in root['/Perms']:
            return True
        fields = reader.get_fields() or {}
        for field in fields.values():
            if str(field.get('/FT', '')) == '/Sig':
                return True
        for page in reader.pages:
            for ref in page.get('/Annots', []):
                annot = ref.get_object()
                if str(annot.get('/FT', '')) == '/Sig':
                    return True
    except Exception:
        # Uninspectable signature structures should not be treated as safe.
        return True
    return False


def info_pdf(data: bytes, password: str = "") -> dict[str, Any]:
    reader = read_pdf(data, password)
    pages = []
    for page in reader.pages:
        rot = int(page.get('/Rotate', 0)) % 360
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        if rot in (90, 270):
            w, h = h, w
        pages.append({'width': round(w, 2), 'height': round(h, 2)})
    return {'pages': len(reader.pages), 'sizes': pages,
            'has_signatures': has_signatures(reader),
            'encrypted': reader.is_encrypted}


def page_numbers(scope: str, expression: str, count: int) -> list[int]:
    if scope in ('all', 'every'):
        return list(range(1, count + 1))
    if scope == 'first':
        return [1]
    if scope == 'last':
        return [count]
    if scope == 'odd':
        return list(range(1, count + 1, 2))
    if scope == 'even':
        return list(range(2, count + 1, 2))
    if scope != 'custom':
        raise DocumentError('页码模式无效。')
    found: set[int] = set()
    if not expression.strip():
        raise DocumentError('请输入指定页码，例如 1,3-5。')
    for part in re.split(r'[,，\s;；]+', expression.strip()):
        if not part:
            continue
        if '-' in part:
            bits = part.split('-')
            if len(bits) != 2 or not all(x.isdigit() for x in bits):
                raise DocumentError(f'页码范围无效：{part}')
            start, stop = map(int, bits)
            if stop < start or stop - start > MAX_PAGES:
                raise DocumentError(f'页码范围无效：{part}')
            found.update(range(start, stop + 1))
        elif part.isdigit():
            found.add(int(part))
        else:
            raise DocumentError(f'页码格式无效：{part}')
    if not found or any(n < 1 or n > count for n in found):
        raise DocumentError(f'指定页码超出文件范围（1–{count}）。')
    return sorted(found)


def bounded(value: Any, low: float, high: float, name: str) -> float:
    try:
        number = float(value)
        if not low <= number <= high:
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError):
        raise DocumentError(f'{name} 必须在 {low}–{high} 范围内。')


def prepare_stamp(data: bytes, white_to_alpha: bool, threshold: int) -> Image.Image:
    try:
        with Image.open(BytesIO(data)) as source:
            if source.width * source.height > 20_000_000:
                raise DocumentError('印章图片尺寸过大（最多 2000 万像素）。')
            image = ImageOps.exif_transpose(source).convert('RGBA')
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        if isinstance(exc, DocumentError):
            raise
        raise DocumentError('印章图片不能读取，请使用 PNG、JPG 或 WebP。') from exc
    if white_to_alpha:
        # Compute a white-key mask with Pillow's native image operators.
        # A soft 28-level transition avoids hard white fringes.
        red, green, blue, alpha = image.split()
        minimum = ImageChops.darker(red, ImageChops.darker(green, blue))
        white_mask = minimum.point(lambda v: 0 if v >= threshold else
                                   255 if v <= threshold - 28 else
                                   round(255 * (threshold - v) / 28))
        image.putalpha(ImageChops.multiply(alpha, white_mask))
    return image


def faded_image(img: Image.Image, opacity: float) -> Image.Image:
    if opacity >= 0.999:
        return img
    im = img.copy()
    a = im.getchannel('A').point(lambda v: round(v * opacity))
    im.putalpha(a)
    return im


def stamp_overlay(page_width: float, page_height: float,
                  commands: list[dict[str, Any]]) -> BytesIO:
    stream = BytesIO()
    c = Canvas(stream, pagesize=(page_width, page_height), pageCompression=1)
    for cmd in commands:
        img = faded_image(cmd['image'], cmd['opacity'])
        x, y, w, h = cmd['x'], cmd['y'], cmd['width'], cmd['height']
        if cmd.get('rotation', 0):
            c.saveState()
            c.translate(x + w / 2, y + h / 2)
            c.rotate(-cmd['rotation'])  # positive values rotate clockwise in browser preview
            c.drawImage(ImageReader(img), -w / 2, -h / 2, width=w, height=h, mask='auto')
            c.restoreState()
        else:
            c.drawImage(ImageReader(img), x, y, width=w, height=h, mask='auto')
    c.showPage()
    c.save()
    stream.seek(0)
    return stream


def distribute_pages(selected: list[int], limit: int) -> list[list[int]]:
    if len(selected) < 2:
        return []
    groups_count = ceil(len(selected) / limit)
    base, excess = divmod(len(selected), groups_count)
    sizes = [base + (i < excess) for i in range(groups_count)]
    if any(s == 1 for s in sizes):
        # For 3 pages with limit 2, prefer one 3-page seal over a useless 1-page seal.
        return [selected]
    result, index = [], 0
    for size in sizes:
        result.append(selected[index:index + size])
        index += size
    return result


def generate_seams(reader: PdfReader, config: dict, raw_images: list[bytes]) -> dict[int, list[dict]]:
    if not config.get('enabled'):
        return {}
    image_index = int(config.get('image_index', 0))
    if not 0 <= image_index < len(raw_images):
        raise DocumentError('骑缝章没有选择有效图片。')
    size = bounded(config.get('size_mm', 40), 10, 100, '骑缝章尺寸') * POINTS_PER_MM
    opacity = bounded(config.get('opacity', 1), 0.05, 1, '骑缝章不透明度')
    position_pct = bounded(config.get('position_percent', 50), 0, 100, '骑缝章位置') / 100
    max_pages = int(bounded(config.get('max_pages', 12), 2, 50, '每组骑缝章页数'))
    location = config.get('position', 'right')
    if location not in ('right', 'left', 'top', 'bottom'):
        raise DocumentError('骑缝章边缘位置无效。')
    image = prepare_stamp(raw_images[image_index], bool(config.get('white_to_alpha', True)),
                          int(bounded(config.get('threshold', 245), 190, 255, '去白阈值')))
    selected = page_numbers(config.get('scope', 'all'), config.get('pages', ''), len(reader.pages))
    cmds: dict[int, list[dict]] = {}
    for group in distribute_pages(selected, max_pages):
        n = len(group)
        for index, page_number in enumerate(group):
            left = round(index * image.width / n)
            right = round((index + 1) * image.width / n)
            if right <= left:
                raise DocumentError('骑缝章图片太窄，不足以分割指定页数。')
            slice_image = image.crop((left, 0, right, image.height))
            page = reader.pages[page_number - 1]
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            slice_w = size * (right - left) / image.width
            slice_h = size * image.height / image.width
            if location == 'right':
                x, y, sw, sh = w - slice_w, (h - slice_h) * (1 - position_pct), slice_w, slice_h
            elif location == 'left':
                x, y, sw, sh = 0, (h - slice_h) * (1 - position_pct), slice_w, slice_h
            else:
                # Rotate individual vertical segment to form a horizontal strip.
                slice_image = slice_image.transpose(Image.Transpose.ROTATE_90)
                sw, sh = slice_h, slice_w
                x = (w - sw) * position_pct
                y = h - sh if location == 'top' else 0
            cmds.setdefault(page_number, []).append({
                'image': slice_image, 'opacity': opacity, 'x': x, 'y': y,
                'width': sw, 'height': sh, 'rotation': 0,
            })
    return cmds


def stamp_pdf(data: bytes, images: list[bytes], config: dict) -> bytes:
    reader = read_pdf(data, str(config.get('input_password', '')))
    signed = has_signatures(reader)
    if signed and not bool(config.get('allow_signature_invalidation')):
        raise DocumentError('原 PDF 含有数字签名。盖章可能使原签名失效；请明确勾选“允许处理已签名文件”。')
    if not images:
        raise DocumentError('至少添加一张印章图片。')
    specs = config.get('stamps') or []
    if not isinstance(specs, list) or len(specs) > MAX_STAMPS:
        raise DocumentError(f'普通章数量最多 {MAX_STAMPS} 个。')
    seam = config.get('seam') or {}
    if not specs and not seam.get('enabled'):
        raise DocumentError('请先添加普通章，或开启骑缝章。')

    writer = PdfWriter()
    writer.append(reader)  # preserve selectable text, bookmarks, links where supported
    for page in writer.pages:
        if int(page.get('/Rotate', 0)) % 360:
            page.transfer_rotation_to_content()
    seam_cmds = generate_seams(writer, seam, images)
    regular_cmds: dict[int, list[dict]] = {}
    for spec in specs:
        idx = int(spec.get('image_index', 0))
        if not 0 <= idx < len(images):
            raise DocumentError('普通章使用的图片不存在。')
        img = prepare_stamp(images[idx], bool(spec.get('white_to_alpha', True)),
                            int(bounded(spec.get('threshold', 245), 190, 255, '去白阈值')))
        size = bounded(spec.get('size_mm', 40), 8, 180, '普通章尺寸') * POINTS_PER_MM
        target_h = size * img.height / img.width
        x_pct = bounded(spec.get('x', 0.5), 0, 1, '横向位置')
        y_pct = bounded(spec.get('y', 0.7), 0, 1, '纵向位置')
        rotation = bounded(spec.get('rotation', 0), -180, 180, '旋转角度')
        opacity = bounded(spec.get('opacity', 1), 0.05, 1, '普通章不透明度')
        for pn in page_numbers(spec.get('scope', 'last'), spec.get('pages', ''), len(writer.pages)):
            pg = writer.pages[pn - 1]
            w, h = float(pg.mediabox.width), float(pg.mediabox.height)
            if size > w or target_h > h:
                raise DocumentError(f'第 {pn} 页比印章小，请缩小印章尺寸。')
            left = (w - size) * x_pct
            top = (h - target_h) * y_pct
            regular_cmds.setdefault(pn, []).append({
                'image': img, 'opacity': opacity, 'x': left, 'y': h - top - target_h,
                'width': size, 'height': target_h, 'rotation': rotation,
            })

    for page_no, pg in enumerate(writer.pages, 1):
        commands = seam_cmds.get(page_no, []) + regular_cmds.get(page_no, [])
        if not commands:
            continue
        overlay_pdf = PdfReader(stamp_overlay(float(pg.mediabox.width),
                                              float(pg.mediabox.height), commands))
        pg.merge_page(overlay_pdf.pages[0], over=True)
    if config.get('output_password'):
        writer.encrypt(str(config['output_password']), algorithm='AES-256')
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()
