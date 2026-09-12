from pathlib import Path
import unittest
from unittest.mock import Mock
from PIL import Image, ImageDraw
from visual import inspect_artwork, dominant_color
from sync import SpotifyScreen

FIXTURES = Path(__file__).parent / 'test_fixtures'


class ArtworkDetectionTests(unittest.TestCase):
    def test_actual_user_player_with_hidden_and_visible_controls(self):
        for name in ('artwork.png', 'artwork-restored.png'):
            color, reason = inspect_artwork(Image.open(FIXTURES / name))
            self.assertIsNotNone(color, reason)
            self.assertTrue(all(abs(a-b) <= 2 for a, b in zip(color, (86, 62, 90))))

    def test_actual_gradient_player(self):
        color, reason = inspect_artwork(Image.open(FIXTURES / 'gradient.png'))
        self.assertIsNotNone(color, reason)

    def test_strong_horizontal_and_vertical_gradient(self):
        image = Image.new('RGB', (320, 200))
        pixels = image.load()
        for y in range(200):
            for x in range(320):
                pixels[x, y] = (30+int(x/4), 25+int(y/3), 80+int(y/4))
        ImageDraw.Draw(image).rectangle((105, 35, 214, 144), fill=(200, 180, 230))
        self.assertIsNotNone(inspect_artwork(image)[0])

    def test_dominant_family_ignores_small_bright_accents(self):
        color = dominant_color([(50, 90, 110)]*30 + [(255, 0, 0)]*5 + [(255, 255, 255)]*3)
        self.assertEqual(color, (50, 90, 110))

    def test_actual_library_is_rejected(self):
        self.assertIsNone(inspect_artwork(Image.open(FIXTURES / 'library.png'))[0])

    def test_resizing_same_layout_does_not_require_display_size(self):
        image = Image.open(FIXTURES / 'artwork.png')
        for size in ((640, 250), (1280, 500), (960, 375)):
            self.assertIsNotNone(inspect_artwork(image.resize(size))[0])

    def test_blank_window_cannot_trigger_sync(self):
        self.assertIsNone(inspect_artwork(Image.new('RGB', (1280, 700), (86, 62, 90)))[0])

    def test_off_center_cover_cannot_trigger_sync(self):
        image = Image.new('RGB', (1280, 700), (86, 62, 90))
        ImageDraw.Draw(image).rectangle((240, 150, 540, 450), fill='white')
        self.assertIsNone(inspect_artwork(image)[0])

    def test_normal_sized_window_detected_without_accessibility(self):
        screen = SpotifyScreen.__new__(SpotifyScreen)
        screen.foreground_app = Mock(side_effect=AssertionError('Must not require foreground'))
        screen.permissions = Mock(return_value=(False, True))
        screen.capture = Mock()
        window = object()
        screen.capture.spotify_window.return_value = window
        screen.capture.capture.return_value = Image.open(FIXTURES / 'artwork.png')
        result, reason = screen.active_window()
        self.assertIs(result, window, reason)
        self.assertIsNotNone(screen.sample(window))
        screen.foreground_app.assert_not_called()



if __name__ == '__main__':
    unittest.main()
