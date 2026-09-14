"""Profile isolation and admission checks; no model, network or engine queries."""
import copy
import hashlib
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from astra_web import chess_game as game
from astra_web.config import APP_ROOT, Config
from astra_web.player_profiles import (
    game_player_binding, get_profile, persona_for, player_prompt, profile_for,
    player_profiles_compatible, profile_identity, verify_game_profile,
    runtime_profile_for_binding, trusted_runtime_profile, GLM_HIGH_PROFILE,
)
from astra_web.supervisor import Supervisor


class ProfileFixture:
    def setUp(self):
        super().setUp()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.data_dir = Path(folder.name)

    def config(self, **kwargs):
        return Config(data_dir=self.data_dir, **kwargs)

    def state(self, config=None, side='black'):
        return game.new_game({'id': 'profile-fixture', 'name': 'Fixture human'},
                             side, config or self.config())

    def legacy_state(self, config=None, *, unprofiled=False):
        config = config or self.config()
        state = self.state(config)
        del state['player_prompt'], state['player_persona']
        del state['player_profile']['persona']
        prompt = (APP_ROOT / 'prompts' / 'legacy' / 'player-v1.md').read_text(encoding='utf-8')
        if config.model_profile != 'astra':
            prompt = prompt.replace('You are Astra,', 'You are GLM 5.3 Flash (z-ai/glm-5.3-flash),')
            prompt = prompt.replace('Astra', 'GLM 5.3 Flash')
            prompt = prompt.replace(
                "The chess tools are exposed through Codex's JavaScript tool orchestration. Use\n"
                'that interface to call the supplied tools; it does not grant general host access.',
                'The chess tools are supplied as named function calls. Call these tools directly;\n'
                'they do not grant general host access.')
        state['player_profile']['prompt_sha256'] = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
        if unprofiled:
            del state['player_profile']
        return state


class PlayerProfileConfigTests(ProfileFixture, unittest.TestCase):
    def test_default_retains_astra_identity_reasoning_and_code_mode(self):
        config = self.config()
        config.validate()
        profile = profile_for(config)
        self.assertEqual(config.model_profile, 'astra')
        self.assertEqual(config.model, 'gpt-6-astra')
        self.assertEqual(config.reasoning, 'ultra')
        self.assertEqual(profile.provider, 'astra_openai')
        self.assertEqual(profile.env_key, 'OPENAI_API_KEY')
        self.assertTrue(profile.code_mode)
        self.assertEqual(profile.context_window, 400_000)
        self.assertEqual(profile.compact_limit, 250_000)

    def test_glm_uses_requested_model_throughput_routing_and_separate_credential(self):
        config = self.config(model_profile='openrouter-glm')
        config.validate()
        profile = profile_for(config)
        self.assertEqual(config.model, 'z-ai/glm-5.3-flash:nitro')
        self.assertEqual(profile.canonical_model, 'z-ai/glm-5.3-flash')
        self.assertEqual(config.reasoning, 'max')
        self.assertEqual(profile.provider, 'chess_openrouter')
        self.assertEqual(profile.base_url, 'https://openrouter.ai/api/v1')
        self.assertEqual(profile.env_key, 'OPENROUTER_API_KEY')
        self.assertEqual(profile.routing, 'throughput-nitro')
        self.assertFalse(profile.code_mode)
        self.assertEqual(profile.context_window, 1_310_720)
        self.assertEqual(profile.compact_limit, 250_000)
        self.assertEqual(profile.version, 4)
        self.assertEqual(profile.max_output_tokens, 32768)

    def test_environment_selects_profile_at_config_creation(self):
        astra = self.config()
        with patch.dict(os.environ, {'ASTRA_MODEL_PROFILE': 'openrouter-glm'}):
            glm = self.config()
            glm.validate()
        self.assertEqual(glm.model_profile, 'openrouter-glm')
        self.assertEqual(glm.model, 'z-ai/glm-5.3-flash:nitro')
        self.assertEqual(astra.model_profile, 'astra')
        self.assertEqual(self.config().model_profile, 'astra')

    def test_unknown_profile_fails_instead_of_falling_back(self):
        for name in ('openrouter', 'OPENROUTER-GLM', '', None):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unknown chess model profile'):
                get_profile(name)
        with patch.dict(os.environ, {'ASTRA_MODEL_PROFILE': 'typo'}):
            with self.assertRaisesRegex(ValueError, 'Unknown chess model profile'):
                self.config()

    def test_explicit_model_and_reasoning_cannot_override_selected_profile(self):
        for overrides in (
            {'model': 'z-ai/glm-5.3-flash:nitro', 'reasoning': 'high'},
            {'model_profile': 'openrouter-glm', 'model': 'gpt-6-astra'},
            {'model_profile': 'openrouter-glm', 'model': 'z-ai/glm-5.3-flash'},
            {'model_profile': 'openrouter-glm', 'reasoning': 'ultra'},
            {'model_profile': 'openrouter-glm', 'reasoning': 'high'},
        ):
            with self.subTest(overrides=overrides):
                config = self.config(**overrides)
                with self.assertRaisesRegex(ValueError, 'must match the selected chess profile'):
                    config.validate()

    def test_legacy_config_without_profile_is_only_compatible_with_astra(self):
        legacy = SimpleNamespace(model='gpt-6-astra', reasoning='ultra')
        self.assertEqual(profile_for(legacy).name, 'astra')
        legacy.model = 'z-ai/glm-5.3-flash:nitro'
        legacy.reasoning = 'high'
        with self.assertRaisesRegex(ValueError, 'must match the selected chess profile'):
            profile_for(legacy)

    def test_glm_experiments_allow_one_or_two_workers(self):
        for count in (0, 3, 16, True, 1.5):
            with self.subTest(count=count):
                with self.assertRaisesRegex(ValueError, 'support one or two workers'):
                    self.config(model_profile='openrouter-glm', max_workers=count).validate()
        self.config(model_profile='openrouter-glm', max_workers=1).validate()
        self.config(model_profile='openrouter-glm', max_workers=2).validate()
        self.config(model_profile='astra', max_workers=2).validate()

    def test_available_uses_only_selected_profiles_credential(self):
        for profile, correct_key, other_key in (
            ('astra', 'OPENAI_API_KEY', 'OPENROUTER_API_KEY'),
            ('openrouter-glm', 'OPENROUTER_API_KEY', 'OPENAI_API_KEY'),
        ):
            with self.subTest(profile=profile):
                supervisor = Supervisor(self.config(model_profile=profile, player_mode='codex'),
                                        Mock(), Mock())
                self.assertFalse(supervisor.available)
                with patch.dict(os.environ, {other_key: 'fixture-unused-key'}):
                    self.assertFalse(supervisor.available)
                with patch.dict(os.environ, {correct_key: 'fixture-selected-key'}):
                    self.assertTrue(supervisor.available)


class PlayerPromptAndPersistenceTests(ProfileFixture, unittest.TestCase):
    def test_shared_method_is_persona_neutral_and_included_in_astra_prompt(self):
        canonical = (APP_ROOT / 'prompts' / 'player.md').read_text(encoding='utf-8')
        self.assertNotIn('Astra', canonical)
        self.assertNotIn('Arcturus', canonical)
        self.assertIn(canonical.rstrip(), player_prompt(get_profile('astra')))

    def test_glm_prompt_identifies_glm_and_explains_direct_chess_tool_calls(self):
        prompt = player_prompt(get_profile('openrouter-glm'))
        self.assertTrue(prompt.startswith('You are Arcturus, an AI chess-playing persona.'))
        self.assertIn('Your actual underlying model is z-ai/glm-5.3-flash.', prompt)
        self.assertNotIn("Codex's JavaScript tool orchestration", prompt)
        self.assertIn('named function calls. Call these tools directly', prompt)
        self.assertIn('Call chess_status at the start of every response attempt', prompt)
        self.assertIn('All game actions use only the supplied chess tools.', prompt)
        self.assertIn('Do not delegate play.', prompt)

    def test_new_games_record_profile_and_effective_model_for_both_player_colors(self):
        for profile in ('astra', 'openrouter-glm'):
            config = self.config(model_profile=profile)
            for human_side in ('white', 'black'):
                with self.subTest(profile=profile, human_side=human_side):
                    state = self.state(config, human_side)
                    identity = state['player_profile']
                    self.assertEqual(identity, profile_identity(config))
                    self.assertEqual(identity['driver'], 'codex-app-server')
                    self.assertEqual(identity['model'], state['model'])
                    self.assertEqual(identity['reasoning'], state['reasoning'])
                    self.assertEqual(identity['prompt_sha256'], hashlib.sha256(
                        player_prompt(profile_for(config)).encode('utf-8')).hexdigest())
                    snapshot = game.model_snapshot(state)
                    self.assertEqual(snapshot['model'], config.model)
                    self.assertEqual(snapshot['reasoning'], config.reasoning)
                    self.assertEqual(snapshot['player_name'], persona_for(config).display_name)
                    self.assertEqual(snapshot['model_name'], profile_for(config).display_name)
                    player_tag = 'Black' if human_side == 'white' else 'White'
                    self.assertIn(f'[{player_tag} "{persona_for(config).display_name}"]', game.pgn(state))
                    verify_game_profile(state, config)

    def test_new_game_cannot_be_created_with_inconsistent_profile(self):
        with self.assertRaisesRegex(ValueError, 'must match the selected chess profile'):
            self.state(self.config(model_profile='openrouter-glm', model='gpt-6-astra'))

    def test_saved_identity_is_independent_and_rejects_configuration_drift(self):
        config = self.config(model_profile='openrouter-glm')
        original = self.state(config)
        changes = {
            'model': 'gpt-6-astra', 'provider': 'astra_openai',
            'base_url': 'https://example.invalid/v1', 'reasoning': 'ultra',
            'routing': 'provider-default', 'code_mode': True,
            'context_window': 400_000, 'compact_limit': 249_999,
            'version': original['player_profile']['version'] + 1, 'max_output_tokens': 16384,
            'prompt_sha256': '0' * 64,
        }
        for key, changed in changes.items():
            with self.subTest(field=key):
                state = copy.deepcopy(original)
                state['player_profile'][key] = changed
                with self.assertRaisesRegex(ValueError, 'Game player profile changed'):
                    verify_game_profile(state, config)
        verify_game_profile(original, config)

    def test_changing_prompt_changes_new_identity_but_preserves_existing_game(self):
        config = self.config(model_profile='openrouter-glm')
        state = self.state(config)
        canonical = (APP_ROOT / 'prompts' / 'player.md').read_text(encoding='utf-8')
        with patch('astra_web.player_profiles.Path.read_text', return_value=canonical + '\nChanged policy.\n'):
            self.assertNotEqual(profile_identity(config)['prompt_sha256'],
                                state['player_profile']['prompt_sha256'])
            verify_game_profile(state, config)
            self.assertEqual(game_player_binding(state, config)['prompt'], state['player_prompt'])
        verify_game_profile(state, config)

    def test_legacy_games_resume_only_with_original_astra_model_and_reasoning(self):
        astra, glm = self.config(), self.config(model_profile='openrouter-glm')
        legacy = self.legacy_state(astra, unprofiled=True)
        verify_game_profile(legacy, astra)
        self.assertEqual(game.snapshot(legacy)['player_name'], 'Astra')
        self.assertIn('[White "Astra"]', game.pgn(legacy))
        for changed in (
            dict(legacy, model='other-model'),
            dict(legacy, reasoning='high'),
            {k: v for k, v in legacy.items() if k != 'model'},
        ):
            with self.subTest(model=changed.get('model'), reasoning=changed['reasoning']):
                with self.assertRaisesRegex(ValueError, 'Game model metadata differs'):
                    verify_game_profile(changed, astra)
        with self.assertRaisesRegex(ValueError, 'Game model metadata differs'):
            verify_game_profile(legacy, glm)
        legacy_glm = self.legacy_state(glm, unprofiled=True)
        with self.assertRaisesRegex(ValueError, 'Legacy game cannot resume'):
            verify_game_profile(legacy_glm, glm)

    def test_new_profile_games_cannot_resume_under_the_other_profile(self):
        astra, glm = self.config(), self.config(model_profile='openrouter-glm')
        for state, config in ((self.state(astra), glm), (self.state(glm), astra)):
            with self.subTest(model=state['model']):
                with self.assertRaisesRegex(ValueError, 'Game model metadata differs'):
                    verify_game_profile(state, config)

    def test_new_game_rejects_top_level_metadata_contradicting_recorded_profile(self):
        for profile in ('astra', 'openrouter-glm'):
            config = self.config(model_profile=profile)
            original = self.state(config)
            for field, replacement in (('model', 'different-model'), ('reasoning', 'low')):
                for remove in (False, True):
                    with self.subTest(profile=profile, field=field, remove=remove):
                        state = copy.deepcopy(original)
                        if remove:
                            del state[field]
                        else:
                            state[field] = replacement
                        self.assertEqual(state['player_profile'], profile_identity(config))
                        with self.assertRaisesRegex(ValueError, 'Game model metadata differs'):
                            verify_game_profile(state, config)


class PlayerRuntimeCompatibilityTests(ProfileFixture, unittest.TestCase):
    def profiles(self):
        current = profile_identity(self.config(model_profile='openrouter-glm'))
        current.update(version=3, reasoning='high', max_output_tokens=8192)
        previous = copy.deepcopy(current)
        previous.update(version=2, context_window=128_000, compact_limit=80_000)
        return previous, current

    def test_exact_v2_to_v3_upgrade_is_allowed_without_mutating_either_identity(self):
        previous, current = self.profiles()
        before = copy.deepcopy((previous, current))
        self.assertTrue(player_profiles_compatible(previous, current))
        self.assertTrue(player_profiles_compatible(previous, copy.deepcopy(previous)))
        self.assertTrue(player_profiles_compatible(current, copy.deepcopy(current)))
        self.assertFalse(player_profiles_compatible(current, previous))
        self.assertEqual((previous, current), before)

    def test_only_complete_exact_known_runtime_upgrade_is_allowed(self):
        previous, current = self.profiles()
        for field, value in (
            ('version', 1), ('version', 2.0), ('version', True),
            ('context_window', 128_001), ('context_window', 128_000.0),
            ('compact_limit', 80_001), ('compact_limit', 80_000.0),
        ):
            with self.subTest(old_field=field, value=value):
                changed = dict(previous, **{field: value})
                self.assertFalse(player_profiles_compatible(changed, current))
        for field, value in (
            ('version', 4), ('version', 3.0), ('context_window', 1_310_719),
            ('context_window', 1_310_720.0), ('compact_limit', 250_001),
            ('compact_limit', 250_000.0),
        ):
            with self.subTest(new_field=field, value=value):
                changed = dict(current, **{field: value})
                self.assertFalse(player_profiles_compatible(previous, changed))
        self.assertFalse(player_profiles_compatible(dict(previous, name='astra'), dict(current, name='astra')))
        for invalid in (None, [], 'profile'):
            self.assertFalse(player_profiles_compatible(invalid, current))

    def test_upgrade_never_waives_other_model_prompt_persona_or_tool_fields(self):
        previous, current = self.profiles()
        changes = {
            'model': 'another-model', 'canonical_model': 'another-model',
            'provider': 'another-provider', 'base_url': 'https://example.invalid',
            'env_key': 'OTHER_KEY', 'reasoning': 'ultra', 'code_mode': True,
            'max_output_tokens': 16384, 'routing': 'provider-default',
            'display_name': 'Another name', 'driver': 'another-driver',
            'prompt_sha256': '0' * 64, 'tool_schema_sha256': '0' * 64,
            'persona': {}, 'unexpected_extra': 'value',
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = copy.deepcopy(previous)
                changed[field] = value
                self.assertFalse(player_profiles_compatible(changed, current))
                changed = copy.deepcopy(previous)
                changed.pop(field, None)
                if field in previous:
                    self.assertFalse(player_profiles_compatible(changed, current))
        self.assertFalse(player_profiles_compatible(dict(current, code_mode=0), current))

    def test_existing_high_games_keep_their_runtime_when_new_default_is_max(self):
        config = self.config(model_profile='openrouter-glm')
        for version in (2, 3):
            for legacy in (False, True):
                with self.subTest(version=version, legacy=legacy):
                    state = self.legacy_state(config) if legacy else self.state(config)
                    state['reasoning'] = 'high'
                    state['player_profile'].update(version=version, reasoning='high', max_output_tokens=8192)
                    if version == 2:
                        state['player_profile'].update(context_window=128_000, compact_limit=80_000)
                    before = copy.deepcopy(state)
                    binding = game_player_binding(state, config)
                    runtime = runtime_profile_for_binding(binding, config)
                    self.assertEqual(runtime, GLM_HIGH_PROFILE)
                    self.assertEqual(binding['profile'], before['player_profile'])
                    self.assertEqual(state, before)
                    self.assertEqual(game.snapshot(state)['reasoning'], 'high')
                    self.assertIn('[Reasoning "high"]', game.pgn(state))
        next_game = self.state(config)
        self.assertEqual(next_game['reasoning'], 'max')
        self.assertEqual(next_game['player_profile']['version'], 4)
        self.assertEqual(runtime_profile_for_binding(game_player_binding(next_game, config), config),
                         get_profile('openrouter-glm'))

    def test_high_to_max_is_not_a_compatible_saved_thread_migration(self):
        high, _ = self.profiles()
        maximum = profile_identity(self.config(model_profile='openrouter-glm'))
        self.assertFalse(player_profiles_compatible(high, maximum))
        self.assertFalse(player_profiles_compatible(dict(high, version=3,
            context_window=1_310_720, compact_limit=250_000), maximum))

    def test_trusted_runtime_rejects_partial_or_unknown_historical_profiles(self):
        from dataclasses import replace
        self.assertTrue(trusted_runtime_profile(GLM_HIGH_PROFILE))
        self.assertTrue(trusted_runtime_profile(get_profile('openrouter-glm')))
        for profile in (replace(GLM_HIGH_PROFILE, max_output_tokens=32768),
                        replace(GLM_HIGH_PROFILE, version=3.0),
                        replace(get_profile('openrouter-glm'), reasoning='high')):
            self.assertFalse(trusted_runtime_profile(profile))
        config = self.config(model_profile='openrouter-glm')
        state = self.state(config)
        for version, effort, output in ((3, 'max', 32768), (4, 'high', 8192), (2, 'max', 32768)):
            changed = copy.deepcopy(state)
            changed['reasoning'] = effort
            changed['player_profile'].update(version=version, reasoning=effort, max_output_tokens=output)
            with self.assertRaises(ValueError):
                game_player_binding(changed, config)


class PlayerProfileAdmissionTests(ProfileFixture, unittest.IsolatedAsyncioTestCase):
    async def test_mismatch_stops_before_resource_reservation_clock_or_player_including_postgame(self):
        config = self.config(model_profile='openrouter-glm')
        for status in ('active', 'finished'):
            for legacy in (False, True):
                for human_side in ('white', 'black'):
                    with self.subTest(status=status, legacy=legacy, human_side=human_side):
                        state = self.state(self.config(), human_side)
                        state['status'] = status
                        if legacy:
                            del state['player_profile']
                        before = copy.deepcopy(state)
                        store, players = Mock(), Mock()
                        store.get.return_value = state
                        supervisor = Supervisor(config, store, Mock(), players)
                        with patch('astra_web.supervisor.game.clock') as clock:
                            with self.assertRaisesRegex(ValueError, 'profile'):
                                await supervisor._active_run(state['id'])
                        store.reserve.assert_not_called()
                        store.mutate.assert_not_called()
                        clock.assert_not_called()
                        players.assert_not_called()
                        self.assertEqual(state, before)

    async def test_matching_profile_reaches_admission_for_active_and_finished_games(self):
        class ReachedAdmission(Exception):
            pass

        for profile in ('astra', 'openrouter-glm'):
            for status in ('active', 'finished'):
                with self.subTest(profile=profile, status=status):
                    config = self.config(model_profile=profile)
                    state = self.state(config)
                    state['status'] = status
                    store, players = Mock(), Mock()
                    store.get.return_value = state
                    store.reserve.side_effect = ReachedAdmission
                    supervisor = Supervisor(config, store, Mock(), players)
                    with self.assertRaises(ReachedAdmission):
                        await supervisor._active_run(state['id'])
                    store.reserve.assert_called_once_with()
                    players.assert_not_called()


if __name__ == '__main__':
    unittest.main()
