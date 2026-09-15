"""Explicit, versioned experimental profiles; no model or provider fallback."""
from dataclasses import asdict, dataclass, replace
import copy
import hashlib
import json
from pathlib import Path
import re


PROMPT_ROOT = Path(__file__).resolve().parents[1] / 'prompts'
LEGACY_PROMPT_SHA256 = '4c5f91671823a7de1acb65b165d8528ff7c1fb751e05c8ec71f2a69258258b9e'


@dataclass(frozen=True)
class PlayerProfile:
    name: str
    provider: str
    base_url: str
    env_key: str
    model: str
    canonical_model: str
    display_name: str
    reasoning: str
    code_mode: bool
    context_window: int
    compact_limit: int
    routing: str
    version: int = 1
    max_output_tokens: int | None = None


PROFILES = {
    'astra': PlayerProfile('astra', 'astra_openai', 'https://api.openai.com/v1',
        'OPENAI_API_KEY', 'gpt-6-astra', 'gpt-6-astra', 'Astra', 'ultra',
        True, 400_000, 250_000, 'provider-default'),
    # Nitro is OpenRouter's documented throughput-sort shortcut. It includes
    # eligible priority endpoints; it does not change the underlying model.
    # Use the verified full context; Mike selected a 250K compaction trigger.
    'openrouter-glm': PlayerProfile('openrouter-glm', 'chess_openrouter',
        'https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY',
        'z-ai/glm-5.3-flash:nitro', 'z-ai/glm-5.3-flash', 'GLM 5.3 Flash',
        'max', False, 1_310_720, 250_000, 'throughput-nitro', version=4, max_output_tokens=32768),
}

# Earlier games retain their actual High/8K experiment settings. The sole
# authorized v2 migration still changes only context limits to this v3 runtime.
GLM_HIGH_PROFILE = replace(PROFILES['openrouter-glm'], reasoning='high',
                           version=3, max_output_tokens=8192)

# Host-selected High turns retain the current game's 32K
# output allowance and identity. This is a runtime policy, not a saved profile
# migration or a selectable new-game model.
GLM_CHAT_PROFILE = replace(PROFILES['openrouter-glm'], reasoning='high')


def move_reasoning_options(state):
    """Advertise only installed v4 GLM settings; old identities stay immutable."""
    saved = state.get('player_profile')
    expected = asdict(PROFILES['openrouter-glm'])
    if not isinstance(saved, dict):
        return []
    try:
        # JSON equality also rejects bool/int and float/int substitutions.
        matches = (json.dumps({key: saved.get(key) for key in expected}, sort_keys=True,
                              allow_nan=False) == json.dumps(expected, sort_keys=True))
    except (TypeError, ValueError):
        return []
    if matches and all(state.get(key) == expected[key] for key in ('model', 'reasoning')):
        return ['high', 'max']
    return []


def move_reasoning_for_game(state):
    """Read the durable host preference without changing original provenance."""
    options = move_reasoning_options(state)
    if not options:
        if 'move_reasoning' in state:
            raise ValueError('Move reasoning selection is unavailable for this game profile')
        return None
    value = state.get('move_reasoning', state['reasoning'])
    if type(value) is not str or value not in options:
        raise ValueError('Move reasoning must be high or max')
    return value


def trusted_runtime_profile(profile):
    """Accept only complete installed profiles, never arbitrary saved settings."""
    if not isinstance(profile, PlayerProfile):
        return False
    try:
        encoded = json.dumps(asdict(profile), sort_keys=True, allow_nan=False)
        return any(encoded == json.dumps(asdict(known), sort_keys=True, allow_nan=False)
                   for known in (*PROFILES.values(), GLM_HIGH_PROFILE, GLM_CHAT_PROFILE))
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True)
class Persona:
    name: str
    display_name: str
    version: int
    source: str
    status: str = 'stable'


PERSONAS = {
    'astra': Persona('astra', 'Astra', 1, 'personas/astra-v1.md'),
    'arcturus': Persona('arcturus', 'Arcturus', 1, 'personas/arcturus-v1.md', 'draft'),
}


def _sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def get_persona(name):
    try:
        return PERSONAS[name]
    except (KeyError, TypeError):
        raise ValueError('Unknown chess player persona') from None


def persona_for(config):
    """Resolve an independent persona selector only when creating a new game."""
    profile = profile_for(config)
    name = getattr(config, 'persona', None)
    if name is None:
        name = 'arcturus' if profile.name == 'openrouter-glm' else 'astra'
    return get_persona(name)


def saved_player_name(state):
    """Public display name from the saved game, never current persona defaults."""
    profile = state.get('player_profile') or {}
    persona = state.get('player_persona') or {}
    name = persona.get('display_name', profile.get('display_name', 'Astra'))
    if (not isinstance(name, str) or not name.strip() or len(name) > 200
            or any(ord(char) < 32 for char in name)):
        raise ValueError('Saved player display name is invalid')
    return name


def get_profile(name='astra'):
    try:
        return PROFILES[name]
    except (KeyError, TypeError):
        raise ValueError('Unknown chess model profile') from None


def profile_for(config):
    profile = get_profile(getattr(config, 'model_profile', 'astra'))
    if (config.model, config.reasoning) != (profile.model, profile.reasoning):
        raise ValueError('Model and reasoning must match the selected chess profile')
    return profile


def _legacy_prompt(profile):
    """Exact pre-persona prompt; never substitute the currently selected persona."""
    prompt = (PROMPT_ROOT / 'legacy' / 'player-v1.md').read_text(encoding='utf-8')
    if _sha(prompt) != LEGACY_PROMPT_SHA256:
        raise ValueError('The immutable legacy player prompt changed')
    if profile.name != 'astra':
        prompt = prompt.replace('You are Astra,', f'You are {profile.display_name} ({profile.canonical_model}),')
        prompt = prompt.replace('Astra', profile.display_name)
    if not profile.code_mode:
        prompt = prompt.replace(
            "The chess tools are exposed through Codex's JavaScript tool orchestration. Use\n"
            "that interface to call the supplied tools; it does not grant general host access.",
            'The chess tools are supplied as named function calls. Call these tools directly;\n'
            'they do not grant general host access.')
    return prompt


def _model_identity(config, profile=None):
    from .codex_bridge import dynamic_tools
    profile = profile or profile_for(config)
    return {**asdict(profile), 'driver': 'codex-app-server',
            'tool_schema_sha256': _sha(json.dumps(dynamic_tools(), sort_keys=True,
                separators=(',', ':')))}


def _compose(profile, persona):
    source = (PROMPT_ROOT / persona.source).read_text(encoding='utf-8')
    integration = (PROMPT_ROOT / 'personas' / 'integration-v1.md').read_text(encoding='utf-8')
    shared = (PROMPT_ROOT / 'player.md').read_text(encoding='utf-8')
    interface = (
        "The chess tools are exposed through Codex's JavaScript tool orchestration. Use\n"
        'that interface to call the supplied tools; it does not grant general host access.'
        if profile.code_mode else
        'The chess tools are supplied as named function calls. Call these tools directly;\n'
        'they do not grant general host access.')
    prompt = (
        f'You are {persona.display_name}, an AI chess-playing persona.\n'
        f'Your actual underlying model is {profile.canonical_model}. The persona name\n'
        'is separate from the model identity and does not change your permissions.\n\n'
        '## Selected persona source\n\n' + source.rstrip() + '\n\n'
        '## Persona integration and precedence\n\n' + integration.rstrip() + '\n\n'
        '## Shared harness rules\n\n' + shared.rstrip() + '\n\n'
        '## Configured tool interface\n\n' + interface + '\n')
    metadata = {**asdict(persona), 'source_sha256': _sha(source),
                'integration_sha256': _sha(integration)}
    return prompt, metadata


def player_prompt(profile, persona=None):
    """Compose a new-game prompt; existing games use game_player_binding instead."""
    if persona is None:
        persona = get_persona('arcturus' if profile.name == 'openrouter-glm' else 'astra')
    if isinstance(persona, str):
        persona = get_persona(persona)
    return _compose(profile, persona)[0]


def new_player_binding(config):
    """Trusted private snapshot captured once when the host creates a game."""
    prompt, persona = _compose(profile_for(config), persona_for(config))
    identity = {**_model_identity(config), 'prompt_sha256': _sha(prompt), 'persona': persona}
    return {'profile': identity, 'prompt': prompt, 'persona': copy.deepcopy(persona)}


def profile_identity(config):
    return new_player_binding(config)['profile']


def player_profiles_compatible(saved, expected):
    """Exact identity equality, plus the one authorized GLM runtime upgrade.

    This does not rewrite provenance or substitute prompt/persona/model/tool
    identity. A v2 game may use the v3 runtime only when its former 128K/80K
    settings and all remaining fields match exactly. Reverse or partial changes
    and unknown future versions remain incompatible.
    """
    if not isinstance(saved, dict) or not isinstance(expected, dict):
        return False

    def equal(left, right):
        try:
            # Unlike Python's numeric equality, this distinguishes bool/int and
            # integer/float profile fields, and rejects non-JSON or NaN values.
            return (json.dumps(left, sort_keys=True, allow_nan=False) ==
                    json.dumps(right, sort_keys=True, allow_nan=False))
        except (TypeError, ValueError):
            return False

    if equal(saved, expected):
        return True
    if saved.get('name') != 'openrouter-glm' or expected.get('name') != 'openrouter-glm':
        return False
    if any(value.get('reasoning') != 'high' or value.get('max_output_tokens') != 8192
           for value in (saved, expected)):
        return False
    old = {'version': 2, 'context_window': 128_000, 'compact_limit': 80_000}
    new = {'version': 3, 'context_window': 1_310_720, 'compact_limit': 250_000}
    if (not equal({key: saved.get(key) for key in old}, old)
            or not equal({key: expected.get(key) for key in new}, new)):
        return False
    return equal({**saved, **new}, expected)


def _validate_persona_snapshot(persona):
    expected = {'name', 'display_name', 'version', 'source', 'status',
                'source_sha256', 'integration_sha256'}
    if (not isinstance(persona, dict) or set(persona) != expected
            or not isinstance(persona['name'], str)
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', persona['name'])
            or type(persona['version']) is not int or not 1 <= persona['version'] <= 1_000_000
            or not isinstance(persona['status'], str)
            or persona['status'] not in {'stable', 'draft', 'legacy'}):
        raise ValueError('Game player persona snapshot is invalid')
    for key in ('display_name', 'source'):
        if (not isinstance(persona[key], str) or not 1 <= len(persona[key]) <= 200
                or any(ord(char) < 32 for char in persona[key])):
            raise ValueError('Game player persona snapshot is invalid')
    for key in ('source_sha256', 'integration_sha256'):
        if not isinstance(persona[key], str) or not re.fullmatch(r'[0-9a-f]{64}', persona[key]):
            raise ValueError('Game player persona snapshot is invalid')


def _game_runtime_profile(saved, config):
    """Select a known runtime; full identity validation follows before use."""
    current = profile_for(config)
    if (current.name == 'openrouter-glm' and isinstance(saved, dict)
            and saved.get('name') == current.name
            and type(saved.get('version')) is int and saved['version'] in (2, 3)):
        return GLM_HIGH_PROFILE
    return current


def game_player_binding(state, config):
    """Verify model/tool invariants and resolve a game's immutable private prompt.

    Current persona defaults and edited persona/shared source files apply only to
    new games. Legacy records resolve the versioned prompt whose hash they saved;
    this helper does not mutate or migrate any game or Codex recovery record.
    """
    saved = state.get('player_profile')
    profile = _game_runtime_profile(saved, config)
    model = _model_identity(config, profile)
    if state.get('model') != profile.model or state.get('reasoning') != profile.reasoning:
        raise ValueError('Game model metadata differs from its configured player profile')
    if 'player_prompt' in state or 'player_persona' in state:
        prompt, persona = state.get('player_prompt'), state.get('player_persona')
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 131072:
            raise ValueError('Game player prompt snapshot is invalid')
        _validate_persona_snapshot(persona)
        expected = {**model, 'prompt_sha256': _sha(prompt), 'persona': persona}
        if not player_profiles_compatible(saved, expected):
            raise ValueError('Game player profile changed; its prompt and persona snapshot must match')
        return {'profile': copy.deepcopy(saved), 'prompt': prompt, 'persona': copy.deepcopy(persona)}

    if saved is None and profile.name != 'astra':
        raise ValueError('Legacy game cannot resume with a different model profile')
    prompt = _legacy_prompt(profile)
    expected = {**model, 'prompt_sha256': _sha(prompt)}
    if saved is not None and not player_profiles_compatible(saved, expected):
        raise ValueError('Game player profile changed; restore its recorded configuration before resuming')
    persona = {'name': 'astra' if profile.name == 'astra' else 'legacy-glm',
               'display_name': profile.display_name, 'version': 1,
               'source': 'legacy/player-v1.md', 'status': 'legacy',
               'source_sha256': LEGACY_PROMPT_SHA256, 'integration_sha256': _sha('')}
    return {'profile': copy.deepcopy(saved if saved is not None else expected),
            'prompt': prompt, 'persona': persona}


def runtime_profile_for_binding(binding, config, *, response_kind=None, move_reasoning=None):
    """Revalidate a private binding and select its host-authorized runtime.

    Max is a new-game default, not a migration for existing High games. Both
    the model driver and gateway consume this same per-action selection. The
    caller supplies the response kind from authoritative game state; neither
    model text nor the model-visible snapshot selects its own reasoning level.
    The optional move preference is captured by the host at worker admission;
    it is never read from model-visible input. None keeps the saved move policy.
    """
    if response_kind is not None and (type(response_kind) is not str
                                     or response_kind not in ('chat', 'move')):
        raise ValueError('Response kind must be chat, move, or None')
    if not isinstance(binding, dict) or not isinstance(binding.get('profile'), dict):
        raise ValueError('Game player binding is invalid')
    saved = binding['profile']
    state = {'model': saved.get('model'), 'reasoning': saved.get('reasoning'),
             'player_profile': saved}
    if 'persona' in saved:
        state.update(player_prompt=binding.get('prompt'), player_persona=binding.get('persona'))
    verified = game_player_binding(state, config)
    if verified != binding:
        raise ValueError('Game player binding differs from its verified snapshot')
    profile = _game_runtime_profile(saved, config)
    if move_reasoning is not None:
        if response_kind is None or profile != PROFILES['openrouter-glm']:
            raise ValueError('Move reasoning selection requires a current GLM response')
        if type(move_reasoning) is not str or move_reasoning not in ('high', 'max'):
            raise ValueError('Move reasoning must be high or max')
    if response_kind == 'chat' and profile == PROFILES['openrouter-glm']:
        return GLM_CHAT_PROFILE
    if response_kind == 'move' and move_reasoning == 'high':
        return GLM_CHAT_PROFILE
    return profile


def verify_game_profile(state, config):
    game_player_binding(state, config)
