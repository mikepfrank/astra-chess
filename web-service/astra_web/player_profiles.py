"""Explicit, versioned experimental profiles; no model or provider fallback."""
from dataclasses import asdict, dataclass
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
    # Start with a conservative usable context, below the advertised 1.3M.
    'openrouter-glm': PlayerProfile('openrouter-glm', 'chess_openrouter',
        'https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY',
        'z-ai/glm-5.3-flash:nitro', 'z-ai/glm-5.3-flash', 'GLM 5.3 Flash',
        'high', False, 128_000, 80_000, 'throughput-nitro', version=2, max_output_tokens=8192),
}


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


def _model_identity(config):
    from .codex_bridge import dynamic_tools
    profile = profile_for(config)
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


def game_player_binding(state, config):
    """Verify model/tool invariants and resolve a game's immutable private prompt.

    Current persona defaults and edited persona/shared source files apply only to
    new games. Legacy records resolve the versioned prompt whose hash they saved;
    this helper does not mutate or migrate any game or Codex recovery record.
    """
    model = _model_identity(config)
    if state.get('model') != config.model or state.get('reasoning') != config.reasoning:
        raise ValueError('Game model metadata differs from its configured player profile')
    saved = state.get('player_profile')
    if 'player_prompt' in state or 'player_persona' in state:
        prompt, persona = state.get('player_prompt'), state.get('player_persona')
        if not isinstance(prompt, str) or not 1 <= len(prompt) <= 131072:
            raise ValueError('Game player prompt snapshot is invalid')
        _validate_persona_snapshot(persona)
        expected = {**model, 'prompt_sha256': _sha(prompt), 'persona': persona}
        if saved != expected:
            raise ValueError('Game player profile changed; its prompt and persona snapshot must match')
        return {'profile': copy.deepcopy(saved), 'prompt': prompt, 'persona': copy.deepcopy(persona)}

    profile = profile_for(config)
    if saved is None and profile.name != 'astra':
        raise ValueError('Legacy game cannot resume with a different model profile')
    prompt = _legacy_prompt(profile)
    expected = {**model, 'prompt_sha256': _sha(prompt)}
    if saved is not None and saved != expected:
        raise ValueError('Game player profile changed; restore its recorded configuration before resuming')
    persona = {'name': 'astra' if profile.name == 'astra' else 'legacy-glm',
               'display_name': profile.display_name, 'version': 1,
               'source': 'legacy/player-v1.md', 'status': 'legacy',
               'source_sha256': LEGACY_PROMPT_SHA256, 'integration_sha256': _sha('')}
    return {'profile': copy.deepcopy(saved if saved is not None else expected),
            'prompt': prompt, 'persona': persona}


def verify_game_profile(state, config):
    game_player_binding(state, config)
