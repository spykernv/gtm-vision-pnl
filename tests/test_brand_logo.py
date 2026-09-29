import io
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import brand_logo

PAGE = '''
<img class="cc-banner-logo" src="https://cdn.example.invalid/pandectes-logo.png" alt="Cookie banner">
<img src="//shop.example.invalid/cdn/shop/files/Shop_logo_blanc.png?v=1&amp;width=5760"
     class="header__logo-image header__logo-image--transparent" alt="">
<img src="//shop.example.invalid/cdn/shop/files/Shop_logo.png?v=1&amp;width=5760" class="header__logo-image" alt="">
<script type="application/ld+json">{"logo": "https://cdn.example.invalid/files/square.png"}</script>
<link rel="apple-touch-icon" href="//shop.example.invalid/cdn/shop/files/favicon.png?width=180">
'''


def png(width, height, colour, alpha=255):
    buf = io.BytesIO()
    Image.new('RGBA', (width, height), colour + (alpha,)).save(buf, 'PNG')
    return buf.getvalue()


class BrandLogoTests(unittest.TestCase):
    def test_header_logo_first_and_banner_or_white_variants_excluded(self):
        found = brand_logo.candidates(PAGE, 'https://shop.example.invalid/')
        self.assertEqual(found[0], ('header-img', 'https://shop.example.invalid/cdn/shop/files/Shop_logo.png?v=1&width=5760'))
        self.assertEqual([m for m, _ in found], ['header-img', 'json-ld', 'apple-touch-icon'])
        self.assertTrue(all('blanc' not in u and 'pandectes' not in u for _, u in found))

    def test_shopify_cdn_width_is_capped(self):
        url = brand_logo.shopify_width('https://shop.example.invalid/cdn/shop/files/Shop_logo.png?v=1&width=5760', 480)
        self.assertTrue(url.endswith('v=1&width=480'))

    def test_dark_logo_is_trimmed_and_sized_for_the_masthead(self):
        canvas = Image.new('RGBA', (600, 200), (0, 0, 0, 0))
        canvas.paste(Image.new('RGBA', (400, 100), (30, 90, 200, 255)), (100, 50))
        buf = io.BytesIO()
        canvas.save(buf, 'PNG')
        data, info = brand_logo.prepare(buf.getvalue(), 'header-img')
        self.assertEqual((info['display_width'], info['display_height']), (144, 36))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (288, 72))

    def test_white_svg_tiny_or_odd_logos_are_refused(self):
        for data, method in ((png(300, 60, (255, 255, 255)), 'header-img'),
                             (png(300, 60, (250, 250, 245)), 'header-img'),
                             (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'header-img'),
                             (png(30, 10, (20, 20, 20)), 'header-img'),
                             (png(900, 60, (20, 20, 20)), 'header-img'),
                             (png(96, 96, (20, 20, 20)), 'apple-touch-icon')):
            with self.assertRaises(ValueError):
                brand_logo.prepare(data, method)


if __name__ == '__main__':
    unittest.main()
