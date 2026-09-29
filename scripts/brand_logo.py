"""Fetch a shop's own logo for the email masthead, or record why there is none.

Reads only the shop's public home page and the image it points to. Candidates, in order:
the header logo image (Shopify themes and common markup), the JSON-LD Organization logo,
then an apple-touch-icon of at least 120 px. A candidate is refused if it is SVG, too
small, too thin or too wide, or too light to read on the ivory paper (a white variant
made for a dark header). The accepted image is trimmed, resized to 2x its display height
and saved as PNG with a provenance file; otherwise logo.json records status "none" and
the email keeps its text descriptor. Nothing is sent and the journal is untouched.

  python -X utf8 scripts/brand_logo.py https://shop.example --brand "Shop"
"""
import argparse
import hashlib
import html
import io
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
LOGOS = ROOT / 'local' / 'email-design' / 'logos'
AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/128.0 Safari/537.36')
DISPLAY_HEIGHT = 36
MAX_DISPLAY_WIDTH = 180
EXCLUDED = re.compile(r'cookie|consent|pandectes|payment|paypal|visa|mastercard|klarna|trustpilot|'
                      r'avis|review|badge|flag-icon|country|blanc|white|transparent|inverse|light', re.I)


def get(url, limit):
    req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept-Language': 'fr-FR,fr;q=0.9'})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = r.read(limit + 1)
        if len(data) > limit:
            raise ValueError('response larger than %d bytes' % limit)
        return r.geturl(), r.headers.get('content-type', ''), data


def attrs(tag):
    return {k.lower(): html.unescape(v) for k, v in re.findall(r'([\w:-]+)\s*=\s*"([^"]*)"', tag)}


def shopify_width(url, width):
    """Ask Shopify's CDN for a raster no wider than needed; other hosts are left as is."""
    parts = urlsplit(url)
    if '/cdn/shop/' not in parts.path and 'cdn.shopify.com' not in parts.netloc:
        return url
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != 'width'] + [('width', str(width))]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ''))


def candidates(page, base):
    found = []
    for m in re.finditer(r'<img\b[^>]*>', page, re.I):
        a = attrs(m.group(0))
        filename = urlsplit(a.get('src', '')).path.rsplit('/', 1)[-1]
        label = ' '.join([a.get('class', ''), a.get('alt', ''), a.get('id', ''), filename])
        if 'logo' not in label.lower() or EXCLUDED.search(label) or not a.get('src'):
            continue
        header = 'header' in a.get('class', '').lower() or 'site-logo' in a.get('class', '').lower()
        found.append((0 if header else 1, 'header-img', urljoin(base, a['src'])))
    for m in re.finditer(r'"logo"\s*:\s*"(https?:[^"]+)"', page):
        found.append((2, 'json-ld', m.group(1).replace('\\/', '/')))
    for m in re.finditer(r'<link\b[^>]*rel="apple-touch-icon[^"]*"[^>]*>', page, re.I):
        href = attrs(m.group(0)).get('href')
        if href:
            found.append((3, 'apple-touch-icon', urljoin(base, href)))
    seen, ordered = set(), []
    for rank, method, url in sorted(found, key=lambda c: c[0]):
        if url not in seen:
            seen.add(url)
            ordered.append((method, url))
    return ordered


def prepare(data, method):
    """Return (png_bytes, info) or raise ValueError with the refusal reason."""
    if data.lstrip()[:5].lower() in (b'<?xml', b'<svg ') or b'<svg' in data[:512].lower():
        raise ValueError('SVG is not rendered by Gmail')
    image = Image.open(io.BytesIO(data))
    image.load()
    rgba = image.convert('RGBA')
    alpha = rgba.getchannel('A')
    light = rgba.convert('L')
    # Content = visible pixels that are not near-white paper.
    mask = Image.eval(alpha, lambda v: 255 if v > 24 else 0)
    dark = Image.eval(light, lambda v: 255 if v < 235 else 0)
    content = Image.composite(dark, Image.new('L', rgba.size, 0), mask)
    box = content.getbbox()
    if not box:
        raise ValueError('no visible dark content (white or empty logo)')
    rgba = rgba.crop(box)
    w, h = rgba.size
    if method == 'apple-touch-icon' and min(image.size) < 120:
        raise ValueError('icon smaller than 120 px')
    if w < 40 or h < 12:
        raise ValueError('logo too small after trimming (%dx%d)' % (w, h))
    ratio = w / h
    if not 0.5 <= ratio <= 8:
        raise ValueError('unusual proportions %.2f' % ratio)
    visible = [lum for lum, a in zip(rgba.convert('L').tobytes(), rgba.getchannel('A').tobytes()) if a > 24]
    mean = sum(visible) / len(visible) / 255
    if mean > 0.82:
        raise ValueError('too light for the ivory paper (mean luminance %.2f)' % mean)
    display_h = DISPLAY_HEIGHT
    display_w = round(display_h * ratio)
    if display_w > MAX_DISPLAY_WIDTH:
        display_w = MAX_DISPLAY_WIDTH
        display_h = max(12, round(display_w / ratio))
    out = rgba.resize((display_w * 2, display_h * 2), Image.LANCZOS)
    buf = io.BytesIO()
    out.save(buf, 'PNG', optimize=True)
    return buf.getvalue(), {'display_width': display_w, 'display_height': display_h,
                            'pixel_size': list(out.size), 'mean_luminance': round(mean, 3),
                            'original_size': list(image.size), 'original_format': image.format}


def fetch(site, brand, out_root=LOGOS):
    parts = urlsplit(site if '://' in site else 'https://' + site)
    domain = parts.netloc.lower().removeprefix('www.')
    folder = out_root / domain
    record = {'brand': brand, 'site': site, 'domain': domain,
              'fetched_at': datetime.now(timezone.utc).isoformat(), 'tried': []}
    try:
        final, ctype, body = get(urlunsplit((parts.scheme or 'https', parts.netloc, parts.path or '/', '', '')), 4_000_000)
        record['page'] = final
        page = body.decode('utf-8', 'replace')
        for method, url in candidates(page, final):
            url = shopify_width(url, 480)
            try:
                _, itype, data = get(url, 3_000_000)
                png, info = prepare(data, method)
            except (OSError, ValueError) as exc:
                record['tried'].append({'method': method, 'url': url, 'refused': str(exc)})
                continue
            folder.mkdir(parents=True, exist_ok=True)
            (folder / 'logo.png').write_bytes(png)
            record.update(status='logo', method=method, source_url=url, content_type=itype,
                          source_sha256=hashlib.sha256(data).hexdigest(),
                          png_sha256=hashlib.sha256(png).hexdigest(), png_bytes=len(png),
                          path=(folder / 'logo.png').relative_to(ROOT).as_posix(), **info)
            break
        else:
            record.update(status='none', reason='no usable candidate on the home page')
    except (OSError, ValueError) as exc:
        record.update(status='none', reason='home page unavailable: ' + str(exc))
    if record['status'] == 'none' and (folder / 'logo.png').exists():
        (folder / 'logo.png').unlink()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'logo.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('site')
    parser.add_argument('--brand', required=True)
    args = parser.parse_args()
    record = fetch(args.site, args.brand)
    print(json.dumps({k: record.get(k) for k in ('status', 'method', 'path', 'display_width',
                                                  'display_height', 'reason', 'tried')},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
