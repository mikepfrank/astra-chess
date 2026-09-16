"""Offline exact-commit regression receipt for the September 15 UI controls.

Use the existing clean-checkout runner; fixtures do not contact providers or
touch installed game data. Invoke from web-service with a full candidate SHA.
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests import check_chat_policy as regression

MODULES = tuple(dict.fromkeys((*regression.MODULES, 'test_move_reasoning',
    'test_operator_monitor', 'test_player_personas', 'test_service',
    'test_evaluations', 'test_replay_archive', 'test_replay_identity',
    'test_replay_branding', 'test_replay_library', 'test_matchup_record')))


def main():
    original = regression.MODULES
    try:
        regression.MODULES = MODULES
        code = regression.main()
    finally:
        regression.MODULES = original
    receipt = json.loads((regression.APP / 'var/chat-tests.json').read_text())
    receipt.update(suite='ui-controls', modules=list(MODULES))
    (regression.APP / 'var/ui-tests.json').write_text(json.dumps(receipt, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
