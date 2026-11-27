"""Offline checks for Quick Settings panel logic (no window, no NetworkManager calls)."""
import importlib.util, unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('panel', Path(__file__).resolve().parents[1] / 'config/desktop/panel.py')
panel = importlib.util.module_from_spec(spec); spec.loader.exec_module(panel)


class Wifi(unittest.TestCase):
    def test_signal_icons(self):
        self.assertTrue(panel.signal_icon(90).endswith('excellent-symbolic'))
        self.assertTrue(panel.signal_icon(10).endswith('weak-symbolic'))

    def test_security_flags(self):
        self.assertFalse(panel.ap_secured(0, 0, 0))
        self.assertTrue(panel.ap_secured(1, 0, 0))
        self.assertTrue(panel.ap_secured(0, 0, 0x100))
        self.assertTrue(panel.ap_enterprise(0, 0x200))
        self.assertFalse(panel.ap_enterprise(0, 0x100))

    def test_one_row_per_ssid_active_first_hidden_dropped(self):
        aps = [{'ssid': 'Home', 'strength': 40}, {'ssid': 'Home', 'strength': 80}, {'ssid': '', 'strength': 99},
               {'ssid': 'Cafe', 'strength': 90}, {'ssid': 'Work', 'strength': 20, 'active': True}]
        nets = panel.best_networks(aps)
        self.assertEqual([n['ssid'] for n in nets], ['Work', 'Cafe', 'Home'])
        self.assertEqual(nets[2]['strength'], 80)


class Clipboard(unittest.TestCase):
    def test_parse_marks_images_and_dedupes(self):
        lines = ['9\thello', '8\t[[ binary data 12 KiB png 100x100 ]]', '7\thello', 'garbage', '6\t[[ binary data 1 KiB zip ]]']
        self.assertEqual(panel.parse_cliphist(lines),
                         [('9', 'hello', False), ('8', '[[ binary data 12 KiB png 100x100 ]]', True),
                          ('6', '[[ binary data 1 KiB zip ]]', False)])




class Placement(unittest.TestCase):
    def test_panels_drop_down_top_right_under_the_bar(self):
        x, y = panel.panel_origin({"x": 0, "y": 0, "width": 1920, "height": 1200, "scale": 1.0}, 400)
        self.assertEqual((x, y), (1920 - 400 - 10, 40))

    def test_second_monitor_and_scaling(self):
        x, y = panel.panel_origin({"x": 1920, "y": 0, "width": 2560, "height": 1600, "scale": 1.25}, 400)
        self.assertEqual((x, y), (1920 + 2048 - 400 - 10, 40))


if __name__ == '__main__': unittest.main()
