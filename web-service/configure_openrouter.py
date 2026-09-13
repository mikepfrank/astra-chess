"""Set up the isolated OpenRouter experiment without paid model requests."""
import argparse
import getpass
from pathlib import Path
import warnings

from astra_web.openrouter_setup import (
    MESSAGES, OpenRouterSetupError, configure_openrouter, _is_windows,
)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--codex-bin", help="Path to the reviewed Codex executable")
    args = parser.parse_args(argv)
    if not _is_windows():
        print(MESSAGES["windows_only"])
        return 1
    try:
        print("The local $50 experiment budget counts increases in both OpenRouter and BYOK usage from the first verified baseline.")
        print("Other use of this key counts too. New actions stop with $5 remaining; in-flight work and reporting delay can overshoot.")
        print("The first model-action preflight establishes the baseline; setup makes no paid requests.")
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("OpenRouter API key (hidden): ")
        budget = configure_openrouter(Path(__file__).resolve().parent, key, args.codex_bin)
        key = None
        print(MESSAGES["saved"])
        print(f"Local lifetime budget: ${budget['limit_usd']:.2f}; remaining: ${budget['remaining_usd']:.2f} (not a provider hard cap).")
        return 0
    except OpenRouterSetupError as error:
        status = error.code
    except (EOFError, getpass.GetPassWarning):
        status = "input_unavailable"
    except KeyboardInterrupt:
        status = "cancelled"
    except Exception:
        # Never print an exception that might embed a credential or HTTP data.
        status = "save_failed"
    print(MESSAGES[status])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
