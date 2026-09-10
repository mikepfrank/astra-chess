"""Read-only HTML mirrors of the published experiments, with a fixed allowlist.

The original collection and replay files remain unchanged in the repository.
Only the served index rewrites the known Netlify links to this site's mirrors.
No game directories, PGNs, JSON evidence, or arbitrary repository paths are served.
"""
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from .config import APP_ROOT, REPO_ROOT
from .replay_library import standalone_response


@dataclass(frozen=True)
class Experiment:
    filename: str
    source: Path
    original_url: str


EXPERIMENTS = (
    Experiment('sven-replay.html', REPO_ROOT / 'replays/replay.html',
               'https://astra-vs-sven.netlify.app/'),
    Experiment('nelson-replay.html', REPO_ROOT / 'replays/nelson-replay.html',
               'https://astra-vs-nelson.netlify.app/'),
    Experiment('wendy-replay.html', REPO_ROOT / 'replays/wendy-replay.html',
               'https://astra-vs-wendy.netlify.app/'),
    Experiment('wally-replay.html', REPO_ROOT / 'replays/wally-replay.html',
               'https://astra-vs-wally.netlify.app/'),
    Experiment('wally-rematch-replay.html', REPO_ROOT / 'replays/wally-rematch-replay.html',
               'https://astra-vs-wally-rematch.netlify.app/'),
    Experiment('wally-engine-replay.html', REPO_ROOT / 'replays/wally-engine-replay.html',
               'https://astra-vs-wally-engine.netlify.app/'),
    Experiment('wally-engine-v02-replay.html', REPO_ROOT / 'replays/wally-engine-v02-replay.html',
               'https://astra-vs-wally-engine-v02.netlify.app/'),
    Experiment('wally-engine-v02-black-replay.html', REPO_ROOT / 'replays/wally-engine-v02-black-replay.html',
               'https://astra-vs-wally-engine-v02-black.netlify.app/'),
    Experiment('li-replay.html', REPO_ROOT / 'replays/li-replay.html',
               'https://astra-vs-li.netlify.app/'),
    Experiment('astra-vs-dr-thanos-2026-09-09.html',
               APP_ROOT / 'replays/astra-vs-dr-thanos-2026-09-09.html',
               'https://astra-vs-human.netlify.app/'),
)
EXPERIMENT_FILES = {entry.filename: entry.source for entry in EXPERIMENTS}
INDEX_SOURCE = REPO_ROOT / 'replays/index.html'


def experiment_index():
    """Preserve the historical ordering and metadata while making links local."""
    html = INDEX_SOURCE.read_text(encoding='utf-8')
    for entry in EXPERIMENTS:
        html = html.replace(f'href="{entry.original_url}"',
                            f'href="/experiments/{entry.filename}"')
    html = html.replace('footer p { margin:0; }',
                        'footer p { margin:0; }\n    footer a { color:var(--accent); }', 1)
    return html.replace('</footer>',
                        '<p><a href="/games/">Public player games</a> '
                        '\u00b7 <a href="/">Play Astra</a></p>\n    </footer>', 1)


def install_experiment_library(app):
    """Register the collection and exactly the allowlisted standalone pages."""
    @app.get('/experiments/')
    @app.get('/experiments/index.html')
    def historical_index():
        return standalone_response(experiment_index())

    @app.get('/experiments/{filename}')
    def historical_replay(filename: str):
        source = EXPERIMENT_FILES.get(filename)
        if source is None or not source.is_file():
            raise HTTPException(404, 'Experiment replay not found.')
        return standalone_response(source.read_text(encoding='utf-8'))
