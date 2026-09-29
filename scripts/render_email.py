"""Render the reusable editorial email locally. No network and no sending."""
import argparse
import base64
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / 'examples' / 'email-editorial-v1.html'
ASSETS = ROOT / 'local' / 'email-design' / 'assets'
LOGOS = ROOT / 'local' / 'email-design' / 'logos'
ACTIVE_STYLE = ROOT / 'local' / 'email-design' / 'active-style.json'


def apply_active_style(data):
    """Apply the locally approved appearance, without replacing message content."""
    if not ACTIVE_STYLE.exists():
        return dict(data)
    style = json.loads(ACTIVE_STYLE.read_text(encoding='utf-8-sig'))
    allowed = {'portrait_path', 'portrait_alt', 'postscript'}
    if not isinstance(style, dict) or set(style) != allowed or any(not isinstance(v, str) or not v.strip() for v in style.values()):
        raise ValueError('Active style must contain only a non-empty portrait_path, portrait_alt and postscript')
    return {**style, **data}


def image_asset(value, root, prefix, label):
    if not value:
        return None
    path = (ROOT / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(label + ' must be in ' + root.relative_to(ROOT).as_posix())
    raw = path.read_bytes()
    if len(raw) > 5_000_000 or not raw:
        raise ValueError(label + ' must be non-empty and below 5 MB')
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        mime = 'image/png'
    elif raw.startswith(b'\xff\xd8\xff'):
        mime = 'image/jpeg'
    else:
        raise ValueError(label + ' must be a PNG or JPEG image')
    return {'path': path, 'raw': raw, 'mime_type': mime,
            'cid': prefix + '-' + hashlib.sha256(raw).hexdigest()[:24] + '@vision-pl.local'}


def portrait_asset(data):
    return image_asset(data.get('portrait_path'), ASSETS, 'portrait', 'Portrait')


def logo_asset(data):
    """Shop logo prepared by scripts/brand_logo.py: a PNG at twice its display size."""
    logo = image_asset(data.get('brand_logo_path'), LOGOS, 'logo', 'Brand logo')
    if logo:
        if logo['mime_type'] != 'image/png':
            raise ValueError('Brand logo must be the PNG prepared by brand_logo.py')
        width, height = int.from_bytes(logo['raw'][16:20], 'big'), int.from_bytes(logo['raw'][20:24], 'big')
        logo.update(width=max(1, width // 2), height=max(1, height // 2))
    return logo


def inline_part(asset):
    return {'mime_type': asset['mime_type'], 'filename': asset['path'].name,
            'content_disposition': 'inline', 'content_id': '<' + asset['cid'] + '>',
            'body': {'base64_url_content': base64.urlsafe_b64encode(asset['raw']).decode('ascii').rstrip('=')}}


def build_payload(markup, data):
    body = {'mime_type': 'text/html', 'charset': 'UTF-8', 'body': {'content': markup}}
    images = [a for a in (portrait_asset(data), logo_asset(data)) if a]
    if not images:
        return body
    return {'mime_type': 'multipart/related', 'parts': [body] + [inline_part(a) for a in images]}


def render(data):
    data = dict(data)
    optional = {'portrait_path', 'portrait_alt', 'postscript', 'brand_logo_path'}
    for key, value in data.items():
        if isinstance(value, str) and key not in {'signature', 'cta_url', 'portrait_path', 'postscript',
                                                  'brand_name', 'brand_logo_path'}:
            value = re.sub(r'\b(?:PnL|PNL)\b', 'P&L', value)
            value = value.replace('8–12 semaines', '8 à 12 semaines').replace('8-12 semaines', '8 à 12 semaines')
            if key == 'subject':
                value = value.replace('P&L.', 'P&L')
            data[key] = value
    template = TEMPLATE.read_text(encoding='utf-8')
    fields = set(re.findall(r'\{\{(\w+)\}\}', template))
    if set(data) - optional != fields or any(not isinstance(v, str) or (k in fields and not v.strip()) for k, v in data.items()):
        raise ValueError('Provide all and only the non-empty template fields: ' + ', '.join(sorted(fields)))
    for key, value in data.items():
        if '{{' in value or '}}' in value or '\x00' in value:
            raise ValueError('Unresolved placeholder or invalid character in ' + key)
    url = urlsplit(data['cta_url'])
    if url.scheme not in {'https', 'mailto'} or not url.path or (url.scheme == 'https' and (not url.hostname or url.username or url.password)):
        raise ValueError('CTA must be an explicit HTTPS or mailto URL')
    if any(c in data['cta_url'] for c in '\r\n\t'):
        raise ValueError('Invalid CTA URL')
    def replace(match):
        key = match.group(1)
        value = html.escape(data[key], quote=True)
        if key not in {'signature', 'cta_url'}:
            value = re.sub(r' ([?!:;])', r'&#8239;\1', value)
        return value if key == 'signature' else value.replace('\n', '<br>')
    markup = re.sub(r'\{\{(\w+)\}\}', replace, template)
    portrait = portrait_asset(data)
    portrait_html = ''
    if portrait:
        alt = html.escape(data.get('portrait_alt') or 'Portrait', quote=True)
        portrait_html = '<td width="106" valign="middle" style="width:106px;padding-right:18px;">' + \
            '<img src="cid:' + portrait['cid'] + '" width="88" height="88" alt="' + alt + \
            '" style="display:block;width:88px;height:88px;border:0;border-radius:4px;"></td>'
    markup = markup.replace('<!--SIGNATURE_PHOTO-->', portrait_html)
    # Masthead right cell: the shop logo when one was prepared, else the text descriptor.
    head, rest = markup.split('<!--MASTHEAD_RIGHT-->', 1)
    descriptor, tail = rest.split('<!--/MASTHEAD_RIGHT-->', 1)
    logo = logo_asset(data)
    if logo:
        descriptor = '<td class="brandlogo" align="right" valign="middle" style="padding-left:16px;">' + \
            '<img src="cid:' + logo['cid'] + '" width="%d" height="%d" alt="' % (logo['width'], logo['height']) + \
            html.escape(data['brand_name'], quote=True) + \
            '" style="display:block;width:%dpx;height:%dpx;border:0;"></td>' % (logo['width'], logo['height'])
    markup = head + descriptor + tail
    ps = data.get('postscript', '').strip()
    ps_html = '<p style="margin:23px 0 0;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:1.8;color:#4b534c;">' + html.escape(ps) + '</p>' if ps else ''
    markup = markup.replace('<!--POSTSCRIPT-->', ps_html)
    text_keys = ['salutation', 'observation', 'question', 'pilot_title', 'pilot_body', 'invitation']
    text = '\n\n'.join(data[k] for k in text_keys)
    text += '\n\n' + data['cta_label'] + ' : ' + data['cta_url']
    text += '\n\n' + '\n\n'.join(data[k] for k in ['closing', 'signature', 'optout']) + '\n'
    if ps:
        text += '\n' + ps + '\n'
    return markup, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    data = apply_active_style(json.loads(args.input.read_text(encoding='utf-8-sig')))
    markup, text = render(data)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'email.html').write_text(markup, encoding='utf-8')
    (args.output_dir / 'email.txt').write_text(text, encoding='utf-8')
    payload = build_payload(markup, data)
    (args.output_dir / 'mime-payload.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    preview = markup
    for asset in (portrait_asset(data), logo_asset(data)):
        if asset:
            preview = preview.replace('cid:' + asset['cid'], asset['path'].as_uri())
    (args.output_dir / 'preview.html').write_text(preview, encoding='utf-8')
    print(json.dumps({'html': str(args.output_dir / 'email.html'), 'bytes': len(markup.encode('utf-8')), 'sent': False}))


if __name__ == '__main__':
    main()
