"""Independent persona selection and immutable game context; no model calls."""
import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from astra_web import chess_game as game
from astra_web.config import APP_ROOT, Config
from astra_web.player_profiles import (
    LEGACY_PROMPT_SHA256, game_player_binding, get_persona, get_profile,
    new_player_binding, persona_for, profile_for, verify_game_profile,
)


class PlayerPersonaTests(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def config(self, **kwargs):
        return Config(data_dir=self.root, **kwargs)

    def state(self, config):
        return game.new_game({'id': 'persona-test', 'name': 'Actual opponent'}, 'black', config)

    def legacy(self, config):
        """Recreate the recorded pre-persona structure, independent of resolver."""
        state = self.state(config)
        del state['player_prompt'], state['player_persona']
        del state['player_profile']['persona']
        text = (APP_ROOT / 'prompts' / 'legacy' / 'player-v1.md').read_text(encoding='utf-8')
        if config.model_profile == 'openrouter-glm':
            text = text.replace('You are Astra,', 'You are GLM 5.3 Flash (z-ai/glm-5.3-flash),')
            text = text.replace('Astra', 'GLM 5.3 Flash').replace(
                "The chess tools are exposed through Codex's JavaScript tool orchestration. Use\n"
                'that interface to call the supplied tools; it does not grant general host access.',
                'The chess tools are supplied as named function calls. Call these tools directly;\n'
                'they do not grant general host access.')
        state['player_profile']['prompt_sha256'] = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return state, text

    def test_persona_defaults_are_separate_from_model_profile(self):
        self.assertEqual(persona_for(self.config()).name, 'astra')
        self.assertEqual(persona_for(self.config(model_profile='openrouter-glm')).name, 'arcturus')
        for model_profile, persona in (('astra', 'arcturus'), ('openrouter-glm', 'astra')):
            with self.subTest(model=model_profile, persona=persona):
                config = self.config(model_profile=model_profile, persona=persona)
                config.validate()
                binding = new_player_binding(config)
                self.assertEqual(persona_for(config).name, persona)
                self.assertEqual(binding['persona']['name'], persona)
                self.assertEqual(binding['profile']['name'], model_profile)
                self.assertIn(f'You are {get_persona(persona).display_name},', binding['prompt'])
                self.assertIn(f'Your actual underlying model is {profile_for(config).canonical_model}.',
                              binding['prompt'])
                for field, expected in asdict(get_profile(model_profile)).items():
                    self.assertEqual(binding['profile'][field], expected)

    def test_persona_environment_selector_and_explicit_override(self):
        with patch.dict(os.environ, {'ASTRA_MODEL_PROFILE': 'openrouter-glm', 'ASTRA_PERSONA': 'astra'}):
            default = self.config()
            explicit = self.config(persona='arcturus')
            self.assertEqual(persona_for(default).name, 'astra')
            self.assertEqual(persona_for(explicit).name, 'arcturus')
        for invalid in ('', 'Arcturus', 'unknown', ['astra']):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, 'Unknown chess player persona'):
                    self.config(persona=invalid).validate()

    def test_supplied_arcturus_draft_is_preserved_verbatim_and_scoped(self):
        source = (APP_ROOT / 'prompts' / 'personas' / 'arcturus-v1.md').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(source.encode('utf-8')).hexdigest(),
                         '304f40730cb7a77126694d0125eb9fa1bafb0cb8e624ae4b5180a7b1028c347a')
        binding = new_player_binding(self.config(model_profile='openrouter-glm'))
        prompt = binding['prompt']
        self.assertIn(source.rstrip(), prompt)
        self.assertEqual(binding['persona']['status'], 'draft')
        # These constraints follow the raw creative text and precede common rules.
        for text in ('lore, not verified game evidence or permissions',
                     'Do not assume the current opponent is Dr. Thanos',
                     'Fresh\nchess_status is authoritative',
                     "Engine scores favor the query root's side to move, not necessarily",
                     'Opening preferences use only your own general chess knowledge',
                     'do not claim to write files, create a',
                     'Do not promise pennies per game'):
            self.assertIn(text, prompt)
        self.assertLess(prompt.index('## Selected persona source'),
                        prompt.index('## Persona integration and precedence'))
        self.assertLess(prompt.index('## Persona integration and precedence'),
                        prompt.index('## Shared harness rules'))

    def test_default_change_affects_only_new_games_including_postgame(self):
        original_config = self.config(model_profile='openrouter-glm')
        changed_config = self.config(model_profile='openrouter-glm', persona='astra')
        state = self.state(original_config)
        before = copy.deepcopy(state)
        for status in ('active', 'finished'):
            with self.subTest(status=status):
                state['status'] = status
                binding = game_player_binding(state, changed_config)
                self.assertEqual(binding['prompt'], before['player_prompt'])
                self.assertEqual(binding['profile'], before['player_profile'])
                self.assertEqual(binding['persona']['name'], 'arcturus')
                self.assertEqual(game.snapshot(state)['player_name'], 'Arcturus')
                self.assertEqual(state, dict(before, status=status))
        next_game = self.state(changed_config)
        self.assertEqual(next_game['player_persona']['name'], 'astra')
        self.assertNotEqual(next_game['player_prompt'], state['player_prompt'])
        self.assertEqual(next_game['model'], state['model'])

    def test_existing_snapshot_does_not_reread_changed_or_removed_source_files(self):
        config = self.config(model_profile='openrouter-glm')
        state = self.state(config)
        with patch('astra_web.player_profiles.Path.read_text', side_effect=AssertionError('No source reload')):
            binding = game_player_binding(state, config)
        self.assertEqual(binding['prompt'], state['player_prompt'])
        self.assertEqual(binding['persona'], state['player_persona'])

    def test_v2_game_uses_v3_runtime_without_replacing_its_prompt_persona_or_provenance(self):
        config = self.config(model_profile='openrouter-glm')
        state = self.state(config)
        state['player_profile'].update(version=2, context_window=128_000, compact_limit=80_000)
        before = copy.deepcopy(state)
        config.persona = 'astra'
        for status in ('active', 'finished'):
            with self.subTest(status=status):
                state['status'] = status
                with patch('astra_web.player_profiles.Path.read_text', side_effect=AssertionError('No source reload')):
                    binding = game_player_binding(state, config)
                self.assertEqual(binding['profile'], before['player_profile'])
                self.assertEqual(binding['profile']['version'], 2)
                self.assertEqual(binding['prompt'], before['player_prompt'])
                self.assertEqual(binding['persona'], before['player_persona'])
                self.assertEqual(state, dict(before, status=status))
        self.assertEqual(profile_for(config).version, 3)
        self.assertEqual(profile_for(config).context_window, 1_310_720)
        self.assertEqual(profile_for(config).compact_limit, 250_000)
        self.assertEqual(new_player_binding(config)['persona']['name'], 'astra')

    def test_pre_persona_v2_game_keeps_legacy_prompt_and_exact_saved_identity(self):
        config = self.config(model_profile='openrouter-glm')
        state, prompt = self.legacy(config)
        state['player_profile'].update(version=2, context_window=128_000, compact_limit=80_000)
        before = copy.deepcopy(state)
        binding = game_player_binding(state, config)
        self.assertEqual(binding['profile'], before['player_profile'])
        self.assertEqual(binding['prompt'], prompt)
        self.assertEqual(binding['persona']['display_name'], 'GLM 5.3 Flash')
        self.assertEqual(state, before)
        state['player_profile']['tool_schema_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Game player profile changed'):
            game_player_binding(state, config)

    def test_legacy_games_keep_exact_identity_and_prompt_despite_new_persona_default(self):
        for model_profile in ('astra', 'openrouter-glm'):
            config = self.config(model_profile=model_profile)
            state, prompt = self.legacy(config)
            before = copy.deepcopy(state)
            config.persona = 'arcturus' if model_profile == 'astra' else 'astra'
            for status in ('active', 'finished'):
                with self.subTest(model=model_profile, status=status):
                    state['status'] = status
                    binding = game_player_binding(state, config)
                    self.assertEqual(binding['profile'], before['player_profile'])
                    self.assertEqual(binding['prompt'], prompt)
                    self.assertEqual(binding['persona']['display_name'], profile_for(config).display_name)
                    self.assertEqual(game.snapshot(state)['player_name'], profile_for(config).display_name)
                    self.assertEqual(state, dict(before, status=status))
            self.assertNotEqual(prompt, new_player_binding(config)['prompt'])

    def test_legacy_source_integrity_is_checked(self):
        config = self.config()
        state, _ = self.legacy(config)
        archived = (APP_ROOT / 'prompts' / 'legacy' / 'player-v1.md').read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(archived.encode('utf-8')).hexdigest(), LEGACY_PROMPT_SHA256)
        with patch('astra_web.player_profiles.Path.read_text', return_value=archived + '\nChanged.'):
            with self.assertRaisesRegex(ValueError, 'immutable legacy player prompt changed'):
                game_player_binding(state, config)

    def test_snapshot_corruption_never_silently_selects_a_new_persona(self):
        config = self.config(model_profile='openrouter-glm')
        original = self.state(config)
        for field in ('player_prompt', 'player_persona', 'player_profile'):
            with self.subTest(missing=field):
                state = copy.deepcopy(original)
                del state[field]
                with self.assertRaises(ValueError):
                    verify_game_profile(state, config)
        for change in ('prompt', 'name', 'metadata', 'hash'):
            state = copy.deepcopy(original)
            if change == 'prompt':
                state['player_prompt'] += '\nChanged.'
            elif change == 'name':
                state['player_persona']['display_name'] = 'Astra'
            elif change == 'metadata':
                state['player_persona']['version'] = True
            else:
                state['player_profile']['persona']['source_sha256'] = '0' * 64
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_game_profile(state, config)

    def test_returned_binding_does_not_alias_saved_metadata(self):
        config = self.config(model_profile='openrouter-glm')
        state = self.state(config)
        before = copy.deepcopy(state)
        binding = game_player_binding(state, config)
        binding['profile']['reasoning'] = 'low'
        binding['persona']['display_name'] = 'Modified'
        self.assertEqual(state, before)

    def test_public_snapshot_exposes_names_but_never_private_prompt_or_source(self):
        state = self.state(self.config(model_profile='openrouter-glm'))
        for snapshot in (game.snapshot(state), game.snapshot(state, internal=True), game.model_snapshot(state)):
            self.assertEqual(snapshot['player_name'], 'Arcturus')
            self.assertEqual(snapshot['model_name'], 'GLM 5.3 Flash')
            self.assertEqual(snapshot['persona_id'], 'arcturus')
            self.assertEqual(snapshot['persona_version'], 1)
            for private in ('player_prompt', 'player_persona', 'player_profile', 'prompt_sha256', 'source_sha256'):
                self.assertNotIn(private, snapshot)
            self.assertNotIn('PERSONA DESCRIPTION', json.dumps(snapshot))
        pgn = game.pgn(state)
        self.assertIn('[White "Arcturus"]', pgn)
        self.assertIn('[Model "z-ai/glm-5.3-flash:nitro"]', pgn)
        self.assertIn('[PlayerPersona "arcturus"]', pgn)
        self.assertIn('[PersonaVersion "1"]', pgn)
        self.assertNotIn('PERSONA DESCRIPTION', pgn)

    def test_tool_schema_change_still_blocks_new_and_legacy_games(self):
        config = self.config(model_profile='openrouter-glm')
        states = [self.state(config), self.legacy(config)[0]]
        with patch('astra_web.codex_bridge.dynamic_tools', return_value=[]):
            for state in states:
                with self.subTest(snapshot='player_prompt' in state):
                    with self.assertRaisesRegex(ValueError, 'Game player profile changed'):
                        game_player_binding(state, config)


if __name__ == '__main__':
    unittest.main()
