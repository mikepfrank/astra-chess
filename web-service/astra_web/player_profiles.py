"""Explicit, versioned experimental profiles; no model or provider fallback."""
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path


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


def player_prompt(profile):
    prompt = (Path(__file__).resolve().parents[1] / 'prompts' / 'player.md').read_text(encoding='utf-8')
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


def profile_identity(config):
    from .codex_bridge import dynamic_tools
    profile = profile_for(config)
    return {**asdict(profile), 'driver': 'codex-app-server',
            'prompt_sha256': hashlib.sha256(player_prompt(profile).encode('utf-8')).hexdigest(),
            'tool_schema_sha256': hashlib.sha256(json.dumps(dynamic_tools(), sort_keys=True,
                separators=(',', ':')).encode('utf-8')).hexdigest()}


def verify_game_profile(state, config):
    expected = profile_identity(config)
    if state.get('model') != config.model or state.get('reasoning') != config.reasoning:
        raise ValueError('Game model metadata differs from its configured player profile')
    saved = state.get('player_profile')
    if saved is None:
        # Only the original fixed Astra identity can resume pre-profile games.
        if (expected['name'] != 'astra' or state.get('model') != config.model
                or state.get('reasoning') != config.reasoning):
            raise ValueError('Legacy game cannot resume with a different model profile')
    elif saved != expected:
        raise ValueError('Game player profile changed; restore its recorded configuration before resuming')
