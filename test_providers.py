import unittest
from unittest.mock import Mock, patch

from providers import HomeAssistantProvider, HueProvider, NanoleafProvider, WLEDProvider, rgb_to_xy


class ProviderTests(unittest.TestCase):
    def test_explicit_entity_fetches_only_requested_light(self):
        provider = HomeAssistantProvider({'address': 'http://ha.local'}, 'secret')
        provider._api = Mock(return_value={'entity_id': 'light.desk', 'state': 'on',
                                         'attributes': {'brightness': 255}})
        lights = provider.lights('light.desk')
        provider._api.assert_called_once_with('GET', 'states/light.desk')
        self.assertEqual(lights[0].brightness, 100)
        with self.assertRaises(ValueError):
            provider.lights('sensor.desk')

    def test_setup_normalizes_provider_addresses(self):
        from nebula_settings import connection_from_input
        self.assertEqual(connection_from_input({'kind': 'hue', 'address': '192.168.1.2'})['address'], 'https://192.168.1.2')
        self.assertEqual(connection_from_input({'kind': 'nanoleaf', 'address': 'panel.local'})['address'], 'http://panel.local:16021')
        with self.assertRaises(ValueError):
            connection_from_input({'kind': 'home_assistant', 'address': 'http://ha.local/lovelace'})

    def test_hue_rgb_conversion_is_bounded(self):
        for color in ((255, 0, 0), (0, 255, 0), (0, 0, 255), (0, 0, 0)):
            x, y = rgb_to_xy(color)
            self.assertTrue(0 <= x <= 1 and 0 <= y <= 1)

    @patch('providers._request', return_value={})
    def test_wled_sends_power_color_and_brightness(self, request):
        provider = WLEDProvider({'address': 'http://wled.local'})
        provider.set_state('device', on=True, rgb=(10, 20, 30), brightness=50, transition=.5)
        self.assertEqual(request.call_args.kwargs['json'],
                         {'transition': 5, 'on': True, 'seg': {'col': [[10, 20, 30]]}, 'bri': 127})

    @patch('providers._request', return_value={})
    def test_nanoleaf_uses_local_state_endpoint(self, request):
        provider = NanoleafProvider({'address': 'http://panel.local:16021'}, 'secret')
        provider.set_state('device', on=False)
        self.assertEqual(request.call_args.args[2], 'http://panel.local:16021/api/v1/secret/state')
        self.assertEqual(request.call_args.kwargs['json'], {'on': {'value': False}})

    def test_home_assistant_discovers_multiple_lights(self):
        provider = HomeAssistantProvider({'address': 'http://ha.local'}, 'secret')
        provider._api = Mock(return_value=[
            {'entity_id': 'light.desk', 'state': 'on', 'attributes': {'friendly_name': 'Desk'}},
            {'entity_id': 'sensor.temp', 'state': '20', 'attributes': {}},
            {'entity_id': 'light.wall', 'state': 'off', 'attributes': {'friendly_name': 'Wall'}},
        ])
        self.assertEqual([light.name for light in provider.lights()], ['Desk', 'Wall'])

    def test_hue_payload_uses_v2_light_resource(self):
        provider = HueProvider({'address': 'https://bridge.local'}, 'secret')
        provider._api = Mock(return_value={})
        provider.set_state('abc', on=True, rgb=(120, 40, 200), brightness=65, transition=.3)
        path = provider._api.call_args.args[1]
        payload = provider._api.call_args.kwargs['json']
        self.assertEqual(path, 'light/abc')
        self.assertEqual(payload['dynamics']['duration'], 300)
        self.assertEqual(payload['dimming']['brightness'], 65)


if __name__ == '__main__':
    unittest.main()
