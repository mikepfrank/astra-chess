"""Compare bounded searches without installing the engine on the measured host.

Run locally, or pipe --emit output to an existing remote Python 3.11+ interpreter.
The emitted program loads only this repository's rules/search/diagnostics in
memory. It makes no network requests, writes no files and uses no model or key.
"""
import argparse
import base64
import hashlib
import inspect
import json
from pathlib import Path


def run_bundle(bundle):
    import base64
    import hashlib
    import json
    import platform
    import sys
    import time
    import types

    package = types.ModuleType('astra_engine')
    package.__path__ = []
    sys.modules['astra_engine'] = package
    for name, source in bundle['modules'].items():
        module = types.ModuleType('astra_engine.' + name)
        module.__file__ = '<in-memory-astra_engine/' + name + '.py>'
        sys.modules[module.__name__] = module
        exec(compile(base64.b64decode(source), module.__file__, 'exec'), module.__dict__)
        setattr(package, name, module)
    from astra_engine.rules import Position
    from astra_engine.search import analyze, probe

    def peak_rss_mib():
        if sys.platform == 'win32':
            import ctypes
            from ctypes import wintypes
            class Counters(ctypes.Structure):
                _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ('PeakWorkingSetSize', 'WorkingSetSize',
                    'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
                    'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
            counter = Counters()
            counter.cb = ctypes.sizeof(counter)
            get_process = ctypes.windll.kernel32.GetCurrentProcess
            get_process.restype = wintypes.HANDLE
            read = ctypes.windll.psapi.GetProcessMemoryInfo
            read.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            if not read(get_process(), ctypes.byref(counter), counter.cb):
                return None
            return round(counter.PeakWorkingSetSize / 2**20, 2)
        import resource
        scale = 2**20 if sys.platform == 'darwin' else 1024
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale, 2)

    print(json.dumps({'environment': {'python': platform.python_version(),
        'system': platform.system(), 'machine': platform.machine()},
        'source_sha256': bundle['source_sha256'],
        'method': 'bounded core search; post-search UI diagnostics excluded'}), flush=True)
    for repeat in range(bundle['repeats']):
        for case in bundle['cases']:
            request = case['request']
            position = Position.from_fen(request['fen'])
            history = [Position.from_fen(fen).repetition_key() for fen in request['history_fens']]
            for uci in request.get('after', []):
                history.append(position.repetition_key())
                position = position.play(position.parse_uci(uci))
            common = dict(max_depth=case['depth'], time_limit=bundle['seconds'], history=history)
            started, cpu_started = time.perf_counter(), time.process_time()
            if request['mode'] == 'probe':
                result = probe(position, request['goal'], max_lines=request['candidates'],
                               proof_only=request.get('proof_only', False), **common)
            else:
                result = analyze(position, multipv=request['candidates'],
                                 root_moves=request.get('root_moves'),
                                 evaluation=request.get('evaluation'),
                                 threat_extensions=request.get('threat_extensions', 0), **common)
            elapsed, cpu = time.perf_counter() - started, time.process_time() - cpu_started
            completed = result.get('completed_depth', result.get('proof_completed_depth'))
            answer = {key: result.get(key) for key in ('candidates', 'lines', 'status', 'proof_status')}
            print(json.dumps({'case': case['name'], 'repeat': repeat + 1,
                'requested_depth': case['depth'], 'completed_depth': completed,
                'timed_out': result['timed_out'], 'nodes': result['nodes'],
                'wall_seconds': round(elapsed, 6), 'cpu_seconds': round(cpu, 6),
                'nodes_per_second': round(result['nodes'] / elapsed),
                'process_peak_rss_mib': peak_rss_mib(),
                'answer_sha256': hashlib.sha256(json.dumps(answer, sort_keys=True).encode()).hexdigest(),
                'proof_status': result.get('proof_status')}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--emit', action='store_true', help='Print a self-contained program instead of running it')
    parser.add_argument('--repeats', type=int, choices=range(1, 4), default=2)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--case', action='append', help='Select a named case; may be repeated')
    parser.add_argument('--depth', type=int, choices=range(1, 33), help='Override the cases\' depth ceilings')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 45:
        parser.error('--seconds must be between 1 and 45 per case')
    app_root = Path(__file__).resolve().parents[1]
    modules = {name: (app_root.parent / 'astra_engine' / (name + '.py')).read_bytes()
               for name in ('rules', 'diagnostics', 'search')}
    bundle = {'modules': {name: base64.b64encode(source).decode() for name, source in modules.items()},
              'source_sha256': {name: hashlib.sha256(source).hexdigest() for name, source in modules.items()},
              'cases': json.loads((app_root / 'benchmarks' / 'capacity-cases.json').read_text(encoding='utf-8')),
              'seconds': args.seconds, 'repeats': args.repeats}
    if args.case:
        if set(args.case) - {case['name'] for case in bundle['cases']}:
            parser.error('Unknown case name')
        bundle['cases'] = [case for case in bundle['cases'] if case['name'] in args.case]
    if args.depth:
        for case in bundle['cases']:
            case['depth'] = args.depth
    if args.emit:
        print(inspect.getsource(run_bundle))
        print('import base64, json')
        encoded = base64.b64encode(json.dumps(bundle).encode()).decode()
        print('run_bundle(json.loads(base64.b64decode(' + repr(encoded) + ')))')
    else:
        run_bundle(bundle)


if __name__ == '__main__':
    main()
