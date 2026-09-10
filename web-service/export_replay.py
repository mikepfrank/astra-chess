"""Export one finished hosted game, or rebuild its standalone replay offline."""
import argparse
import json
from pathlib import Path

from astra_web.replay_archive import APP_ROOT, build_archive, load_record, make_record, read_game, record_pgn


def _check_destinations(inputs, outputs):
    """Protect source files and prevent one export artifact replacing another."""
    protected = [(label, Path(path).resolve()) for label, path in inputs]
    for label, path in outputs:
        resolved = Path(path).resolve()
        for other_label, other in protected:
            same = resolved == other
            if not same:
                try:
                    # resolve also follows directory symlinks; samefile adds
                    # existing hard-link aliases where the filesystem supports it.
                    same = resolved.samefile(other)
                except (FileNotFoundError, NotADirectoryError):
                    pass
            if same:
                raise ValueError(f'{label} conflicts with {other_label}; use separate files.')
        protected.append((label, resolved))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--game', help='Finished hosted game ID to read from SQLite in read-only mode')
    source.add_argument('--from-record', type=Path, help='Rebuild from sanitized archive JSON; no database needed')
    parser.add_argument('--data-dir', type=Path, default=APP_ROOT / 'var')
    parser.add_argument('--record', type=Path, help='Sanitized public archive JSON output')
    parser.add_argument('--output', type=Path, help='Standalone HTML output')
    parser.add_argument('--pgn', type=Path, help='Optional separate PGN output')
    parser.add_argument('--record-only', action='store_true', help='Validate and save the public JSON without building HTML')
    parser.add_argument('--omit-commentary', action='store_true', help='Exclude all conversation text from the HTML and JSON outputs')
    args = parser.parse_args(argv)
    try:
        record = load_record(args.from_record) if args.from_record else make_record(read_game(args.data_dir, args.game), args.data_dir)
        if args.omit_commentary:
            record['messages'] = []
        output = args.output or APP_ROOT / 'replays' / ('hosted-' + record['game']['id'] + '.html')
        record_path = args.record or (output.with_suffix('.json') if not args.from_record else None)
        if args.record_only and record_path is None:
            raise ValueError('--record-only with --from-record requires a --record output path.')
        inputs = [('source archive', args.from_record)] if args.from_record else [
            ('source database' + suffix, args.data_dir / ('astra.sqlite3' + suffix))
            for suffix in ('', '-wal', '-shm')]
        outputs = [] if args.record_only else [('HTML output', output)]
        if record_path:
            outputs.append(('JSON record output', record_path))
        if args.pgn:
            outputs.append(('PGN output', args.pgn))
        _check_destinations(inputs, outputs)
        if not args.record_only:
            build_archive(record, output)
        if record_path:
            record_path.parent.mkdir(parents=True, exist_ok=True)
            record_path.write_text(json.dumps(record, indent=2, ensure_ascii=False, allow_nan=False) + '\n', encoding='utf-8')
        if args.pgn:
            args.pgn.parent.mkdir(parents=True, exist_ok=True)
            args.pgn.write_text(record_pgn(record), encoding='utf-8')
        print(f"Archived {len(record['moves'])} plies, {len(record['messages'])} public messages and {len(record['evaluations'])} Astra evaluation slots.")
        if record_path:
            print(f'Public record: {record_path}')
        if not args.record_only:
            print(f'Standalone replay: {output}')
    except (ValueError, OSError) as error:
        parser.exit(1, f'Archive export failed: {error}\n')


if __name__ == '__main__':
    main()
