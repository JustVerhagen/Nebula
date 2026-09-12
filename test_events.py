import unittest
from events import Schedule


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.now = 0
        self.schedule = Schedule(clock=lambda: self.now)

    def test_track_change_interrupts_slow_wait(self):
        self.now = 10
        self.schedule.sampled()
        self.assertEqual(self.schedule.due, 15)
        self.now = 11
        self.assertTrue(self.schedule.playback({'Track ID': 'new', 'Player State': 'Playing'}))
        self.assertLessEqual(self.schedule.due, 11.05)
        self.schedule.sampled()
        self.assertEqual(self.schedule.due, 11.25)

    def test_burst_returns_to_slow_checks(self):
        self.schedule.trigger()
        self.now = 5
        self.schedule.sampled()
        self.assertEqual(self.schedule.due, 10)

    def test_position_updates_do_not_extend_burst(self):
        self.schedule.playback({'Track ID': 'a', 'Player State': 'Playing', 'Playback Position': 1})
        deadline = self.schedule.fast_until
        self.now = 2
        self.assertFalse(self.schedule.playback({'Track ID': 'a', 'Player State': 'Playing', 'Playback Position': 2}))
        self.assertEqual(self.schedule.fast_until, deadline)

    def test_skip_and_pause_resume_trigger_without_song_timer(self):
        for info in ({'Track ID': 'a', 'Player State': 'Playing'},
                     {'Track ID': 'b', 'Player State': 'Playing'},
                     {'Track ID': 'b', 'Player State': 'Paused'},
                     {'Track ID': 'b', 'Player State': 'Playing'}):
            self.assertTrue(self.schedule.playback(info))
        self.assertEqual(self.schedule.events, 4)

    def test_network_failure_backs_off(self):
        self.schedule.backoff()
        self.assertEqual(self.schedule.due, 15)
        self.assertEqual(self.schedule.fast_until, 0)


if __name__ == '__main__':
    unittest.main()
