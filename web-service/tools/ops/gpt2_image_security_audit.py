"""Compare staged image Debian source versions with the saved official tracker.

This is a package inventory assessment, not a claim of application reachability
or an exhaustive scan of statically linked/native Codex dependencies.
"""
from pathlib import Path
import datetime
import hashlib
import json
import subprocess

ROOT = Path('/home/ec2-user/chess-security-stage-20261116/gpt2-image')
BASELINE = ROOT / 'baseline-inventory.json'
CANDIDATE = ROOT / 'candidate-inventory.json'
TRACKER = ROOT / 'debian-security-tracker.json'

COMPARE = r'''
import json,subprocess,sys
data=json.load(sys.stdin)
result={}
for label,packages in data['inventories'].items():
 findings=[]
 for source,version in packages.items():
  for cve,vuln in data['tracker'].get(source,{}).items():
   info=vuln.get('releases',{}).get('bookworm')
   if not info:continue
   fixed=info.get('fixed_version')
   if fixed=='0':continue
   if fixed and info.get('status')=='resolved':
    if subprocess.run(['dpkg','--compare-versions',version,'lt',fixed]).returncode:continue
   elif info.get('status') not in ('open','undetermined'):continue
   findings.append({'source':source,'installed_source_version':version,'cve':cve,'status':info.get('status'),'urgency':info.get('urgency'),'fixed_version':fixed,'nodsa':info.get('nodsa'),'nodsa_reason':info.get('nodsa_reason')})
 result[label]=findings
print(json.dumps(result))
'''

def main():
    inventories = {}
    for label,path in [('baseline',BASELINE),('candidate',CANDIDATE)]:
        inventories[label]={p['source']:p['source_version'] for p in json.loads(path.read_text())['packages']}
    all_sources=set(inventories['baseline'])|set(inventories['candidate'])
    tracker=json.loads(TRACKER.read_text())
    subset={k:tracker[k] for k in sorted(all_sources) if k in tracker}
    payload=json.dumps({'inventories':inventories,'tracker':subset})
    result=subprocess.run(['sudo','docker','run','--rm','-i','--network','none',
        '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
        '--memory','256m','--memory-swap','256m','--cpus','0.5','--pids-limit','64',
        '--entrypoint','python3','gpt2-codex-security:20261116-node22.23.5','-c',COMPARE],
        input=payload,text=True,capture_output=True,check=True,timeout=180)
    findings=json.loads(result.stdout)
    report={'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'source':'https://security-tracker.debian.org/tracker/data/json',
            'source_sha256':hashlib.sha256(TRACKER.read_bytes()).hexdigest(),
            'scope':'Installed Debian source-package versions; no native Codex dependency scan or reachability claim',
            'findings':findings}
    summary={label:{'total':len(rows),'high_or_critical':[r for r in rows if (r.get('urgency') or '').split()[0] in ('high','critical')]} for label,rows in findings.items()}
    report['summary']=summary
    (ROOT/'debian-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
