"""Two native Codex processes, isolated homes, and simultaneous mocked requests.

No live game, real credential, or external provider is used. Each process makes
one tool-assisted turn, exits, and resumes the same private thread in a fresh
process. Rendezvous inside the mocked upstream proves concurrent requests at
both the initial turn and restart, rather than merely concurrent task creation.
"""
import argparse
import asyncio
import json
from pathlib import Path
import time
from urllib.parse import urlparse

from audit_reasoning_roundtrip import TOOL_RESULT, audit_case, bridge


class RequestRendezvous:
    """Keep the first request pending until both native clients have arrived."""

    def __init__(self):
        self.events = {serial: asyncio.Event() for serial in (1, 3)}
        self.arrivals = {serial: {} for serial in (1, 3)}
        self.evidence = []

    async def observe(self, case, serial, process, identity):
        if serial not in self.events:
            return
        arrivals = self.arrivals[serial]
        if case in arrivals or process is None or process.returncode is not None:
            raise bridge.CodexError('Parallel fixture has a duplicate or inactive client')
        arrivals[case] = (process, identity, time.monotonic())
        if len(arrivals) == 2:
            clients = list(arrivals.values())
            checks = {
                'both_processes_alive': all(child.returncode is None for child, _, _ in clients),
                'distinct_processes': len({child.pid for child, _, _ in clients}) == 2,
                'distinct_homes': len({item['codex_home'] for _, item, _ in clients}) == 2,
                'distinct_threads': len({item['thread_id'] for _, item, _ in clients}) == 2,
                'distinct_ports': len({urlparse(item['gateway_base_url']).port
                                       for _, item, _ in clients}) == 2,
                'distinct_gateway_tokens': len({item['gateway_token_sha256']
                                                for _, item, _ in clients}) == 2,
            }
            self.evidence.append({'request_serial': serial,
                'pending_upstream_requests': len(arrivals),
                'arrival_gap_seconds': abs(clients[1][2] - clients[0][2]), **checks})
            if not all(checks.values()):
                raise bridge.CodexError('Parallel fixture process isolation differs')
            self.events[serial].set()
        await asyncio.wait_for(self.events[serial].wait(), 15)


async def audit(codex, version, audit_dir):
    if version not in bridge.reviewed_versions('openrouter-glm'):
        raise bridge.CodexError('Parallel fixture requires an audited CLI version')
    audit_dir = Path(audit_dir).resolve()
    audit_dir.mkdir(parents=True, exist_ok=True)
    rendezvous = RequestRendezvous()

    async def run_case(case):
        async def upstream(serial, process, identity):
            await rendezvous.observe(case, serial, process, identity)
        return await audit_case(codex, version, audit_dir, 'combined',
            tool_result={**TOOL_RESULT, 'isolated_fixture': case}, upstream_observer=upstream)

    cases = await asyncio.gather(run_case('player-a'), run_case('player-b'))
    # Exact case-specific tool results survive both subsequent requests and the
    # process restart. A response belonging to the other case fails this check.
    completed = all(case['audit_completed'] and case['all_status_snapshots_preserved']
                    and case['all_reasoning_fields_preserved'] for case in cases)
    checks = ('both_processes_alive', 'distinct_processes', 'distinct_homes',
              'distinct_threads', 'distinct_ports', 'distinct_gateway_tokens')
    overlap = (len(rendezvous.evidence) == 2
               and all(row['pending_upstream_requests'] == 2
                       and all(row[key] for key in checks) for row in rendezvous.evidence))
    return {'audit_completed': completed and overlap,
            'external_provider_contacted': False, 'real_credentials_inherited': False,
            'parallelism_proven_before_and_after_restart': overlap,
            'rendezvous': rendezvous.evidence, 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--candidate-version', default='0.154.0')
    parser.add_argument('--audit-dir', type=Path, required=True)
    args = parser.parse_args()
    report = asyncio.run(audit(args.codex, args.candidate_version, args.audit_dir))
    (args.audit_dir / 'parallel-audit.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if report['audit_completed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
