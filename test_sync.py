import unittest
from unittest.mock import Mock, patch
from sync import ColorGate, HomeAssistant, median_color, validate_address, setup, SpotifyScreen, ArtworkExit


class SyncTests(unittest.TestCase):
    def test_warm_white_uses_temperature_and_preserves_brightness(self):
        client = self.client('on')
        client.state.return_value = {'state': 'on', 'attributes': {'supported_color_modes': ['color_temp', 'xy']}}
        self.assertTrue(client.warm())
        client.request.assert_called_once_with('POST', 'services/light/turn_on', json={
            'entity_id': 'light.desk', 'transition': 1.2, 'color_temp_kelvin': 3000})

    def test_warm_white_falls_back_to_rgb(self):
        client = self.client('on')
        self.assertTrue(client.warm())
        self.assertEqual(client.request.call_args.kwargs['json']['rgb_color'], [255, 205, 155])

    def test_warm_restore_does_not_turn_on_off_strip(self):
        client = self.client('off')
        self.assertFalse(client.warm())
        client.request.assert_not_called()

    def test_exit_requires_confirmation_and_only_restores_once(self):
        now = [0]
        transition = ArtworkExit(clock=lambda: now[0])
        self.assertFalse(transition.missing())
        transition.seen()
        self.assertFalse(transition.missing())
        now[0] = 1
        self.assertFalse(transition.missing())
        transition.seen()  # A temporary loading frame recovered: do not restore.
        now[0] = 2
        self.assertFalse(transition.missing())
        now[0] = 4
        self.assertTrue(transition.missing())
        transition.restored()
        self.assertFalse(transition.missing())

    def test_foreground_detection_processes_app_switch_events(self):
        screen = SpotifyScreen.__new__(SpotifyScreen)
        screen.Foundation = Mock()
        screen.workspace = Mock()
        pending = iter(['VS Code', 'Spotify', 'VS Code'])
        def deliver_events(_):
            screen.workspace.frontmostApplication.return_value = next(pending)
        screen.Foundation.NSRunLoop.currentRunLoop.return_value.runUntilDate_.side_effect = deliver_events
        self.assertEqual(screen.foreground_app(), 'VS Code')
        self.assertEqual(screen.foreground_app(), 'Spotify')
        self.assertEqual(screen.foreground_app(), 'VS Code')

    def test_address_accepts_saved_url_and_rejects_typo_or_entity(self):
        self.assertEqual(validate_address(' http://homeassistant.local:8123/ '),
                         'http://homeassistant.local:8123')
        for invalid in ('htto://homeassistant.local:8123', 'light.light'):
            with self.assertRaisesRegex(ValueError, 'ADDRESS'):
                validate_address(invalid)

    def test_setup_retries_address_before_asking_for_entity(self):
        config = {'home_assistant_url': 'http://homeassistant.local:8123', 'entity_id': 'light.light'}
        with patch('builtins.input', side_effect=['htto://homeassistant.local:8123', '', '']) as ask, \
                patch('sync.getpass.getpass', return_value=''), patch('builtins.print'):
            with self.assertRaisesRegex(ValueError, 'No token'):
                setup(config)
        prompts = [c.args[0] for c in ask.call_args_list]
        self.assertIn('address', prompts[0])
        self.assertIn('address', prompts[1])
        self.assertIn('Strip entity', prompts[2])
        self.assertEqual(config['entity_id'], 'light.light')

    def test_waits_for_stable_color_and_ignores_small_changes(self):
        gate = ColorGate(12)
        self.assertFalse(gate.candidate((120, 30, 40)))
        self.assertTrue(gate.candidate((121, 31, 41)))
        gate.sent = (121, 31, 41)
        self.assertFalse(gate.candidate((123, 32, 40)))
        self.assertFalse(gate.candidate((20, 90, 180)))
        self.assertTrue(gate.candidate((21, 91, 180)))

    def test_reentry_sends_even_if_same_color(self):
        gate = ColorGate(12)
        gate.sent = (10, 20, 30)
        gate.reset()
        self.assertFalse(gate.candidate((10, 20, 30)))
        self.assertTrue(gate.candidate((10, 20, 30)))

    def test_median_rejects_bright_overlay_outlier(self):
        self.assertEqual(median_color([(20, 30, 40)] * 3 + [(255, 255, 255)]), (20, 30, 40))

    def client(self, state):
        client = HomeAssistant.__new__(HomeAssistant)
        client.config = {'entity_id': 'light.desk', 'transition_seconds': 1.5}
        client.state = Mock(return_value={'state': state})
        client.request = Mock()
        return client

    def test_off_unavailable_unknown_never_receive_color_command(self):
        for state in ('off', 'unavailable', 'unknown'):
            client = self.client(state)
            self.assertFalse(client.color((20, 30, 40)))
            client.request.assert_not_called()

    def test_color_command_targets_only_strip_preserves_brightness(self):
        client = self.client('on')
        self.assertTrue(client.color((20, 30, 40)))
        client.request.assert_called_once_with('POST', 'services/light/turn_on', json={
            'entity_id': 'light.desk', 'rgb_color': [20, 30, 40], 'transition': 1.5})

    def test_failed_state_read_cannot_write(self):
        client = self.client('on')
        client.state.side_effect = TimeoutError()
        with self.assertRaises(TimeoutError):
            client.color((20, 30, 40))
        client.request.assert_not_called()

    def test_redirect_not_followed_with_token(self):
        client = HomeAssistant.__new__(HomeAssistant)
        client.base = 'http://example.invalid:8123'
        client.session = Mock()
        client.session.request.return_value.status_code = 302
        with self.assertRaises(RuntimeError):
            client.request('GET', 'states/light.desk')
        self.assertFalse(client.session.request.call_args.kwargs['allow_redirects'])


if __name__ == '__main__':
    unittest.main()
