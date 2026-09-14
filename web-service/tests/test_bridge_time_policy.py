"""The provider-process bound must not override a host-owned chess clock."""
import unittest
from types import SimpleNamespace

from astra_web import codex_bridge as bridge
from astra_web.player_profiles import get_profile


class BridgeTimePolicyTests(unittest.TestCase):
    def test_earned_openrouter_clock_can_exceed_default_transport_timeout(self):
        value = bridge._action_timeout_seconds(SimpleNamespace(), get_profile('openrouter-glm'),
                                              {'hard_response_seconds': 5400})
        self.assertEqual(value, 5700)

    def test_other_profiles_chat_and_maintenance_keep_their_existing_bound(self):
        config = SimpleNamespace(codex_timeout_seconds=300)
        for profile, snapshot, compact_only in ((get_profile('astra'), {'hard_response_seconds': 5400}, False),
                (get_profile('openrouter-glm'), {}, False),
                (get_profile('openrouter-glm'), {'hard_response_seconds': 5400}, True)):
            self.assertEqual(bridge._action_timeout_seconds(config, profile, snapshot,
                             compact_only=compact_only), 300)

    def test_model_or_malformed_values_cannot_supply_an_unbounded_clock(self):
        for value in (True, '5400', -1, 0, float('nan'), float('inf'), 86401):
            with self.assertRaises(bridge.CodexError):
                bridge._action_timeout_seconds(SimpleNamespace(), get_profile('openrouter-glm'),
                                              {'hard_response_seconds': value})


if __name__ == '__main__':
    unittest.main()
