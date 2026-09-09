"""Run in a terminal to validate and save a Windows-user API credential."""
import argparse
import getpass
from pathlib import Path
import warnings

from astra_web.local_setup import MESSAGES, configure_local, _is_windows


def main(argv=None):
    parser = argparse.ArgumentParser(description="Configure local Astra testing without putting an API key in files or command arguments.", allow_abbrev=False)
    parser.add_argument("--codex-bin", help="Path to the reviewed Codex executable")
    args = parser.parse_args(argv)
    if not _is_windows():
        print(MESSAGES["windows_only"])
        return 1
    try:
        # getpass normally falls back to echoed input. Refuse that fallback.
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            key = getpass.getpass("OpenAI API key (hidden): ")
        status = configure_local(Path(__file__).resolve().parent, key, args.codex_bin)
        key = None
    except (EOFError, getpass.GetPassWarning):
        status = "input_unavailable"
    except KeyboardInterrupt:
        status = "cancelled"
    except Exception:
        # Do not print exceptions: HTTP/client failures can contain credentials.
        status = "save_failed"
    print(MESSAGES[status])
    return 0 if status == "saved" else 1


if __name__ == "__main__":
    raise SystemExit(main())
