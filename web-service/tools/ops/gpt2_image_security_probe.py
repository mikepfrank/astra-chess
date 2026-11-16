"""No-key/no-network probes of both GPT-2 sandbox images, without host mounts."""
from pathlib import Path
import datetime
import json
import subprocess

ROOT = Path('/home/ec2-user/chess-security-stage-20261116/gpt2-image')
PROBE = r'''
import os,pathlib,subprocess,json,selectors,time,hashlib
home=pathlib.Path('/probe-home');(home/'codex').mkdir();workspace=home/'workspace';workspace.mkdir()
os.environ.update(HOME=str(home),CODEX_HOME=str(home/'codex'),NO_COLOR='1')
out={'uid':os.getuid(),'credentials_inherited':any(k in os.environ for k in ['OPENAI_API_KEY','OPENROUTER_API_KEY','GPT2_PROXY_TOKEN'])}
status=pathlib.Path('/proc/self/status').read_text().splitlines()
out['security']={line.split(':',1)[0]:line.split(':',1)[1].strip() for line in status if line.startswith(('CapEff:','NoNewPrivs:','Seccomp:'))}
try:pathlib.Path('/etc/gpt2-probe').write_text('probe');out['root_write_blocked']=False
except OSError as e:out['root_write_blocked']=True;out['root_write_errno']=e.errno
b=subprocess.run(['bwrap','--unshare-user','--unshare-net','--ro-bind','/','/','--tmpfs','/tmp','/bin/true'],text=True,capture_output=True,timeout=10)
out['nested_bubblewrap']={'exit_code':b.returncode,'stderr':b.stderr.strip()}
c=subprocess.run(['codex','sandbox','--','/bin/true'],text=True,capture_output=True,timeout=15,cwd=workspace)
out['codex_linux_sandbox']={'exit_code':c.returncode,'stderr':c.stderr.strip()}
schema=home/'schema'
s=subprocess.run(['codex','app-server','generate-json-schema','--out',str(schema)],text=True,capture_output=True,timeout=20)
out['schema']={'exit_code':s.returncode,'file_count':len(list(schema.rglob('*.json'))),'tree_sha256':hashlib.sha256(''.join(str(p.relative_to(schema))+hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(schema.rglob('*.json'))).encode()).hexdigest()}
p=subprocess.Popen(['codex','app-server','--stdio','--strict-config'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=workspace)
try:
 p.stdin.write(json.dumps({'id':1,'method':'initialize','params':{'clientInfo':{'name':'gpt2-security-probe','title':'GPT-2 staging','version':'1'}}})+'\n');p.stdin.flush()
 sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ);response=None;deadline=time.monotonic()+15
 while time.monotonic()<deadline:
  if sel.select(timeout=1):
   line=p.stdout.readline()
   if not line:break
   item=json.loads(line)
   if item.get('id')==1:response=item;break
 out['initialize']={'passed':bool(response and 'result' in response),'result_keys':sorted(response.get('result',{})) if response else [],'error':response.get('error') if response else 'no_response'}
finally:
 p.terminate()
 try:p.communicate(timeout=5)
 except subprocess.TimeoutExpired:p.kill();p.communicate(timeout=5)
out['passed']=out['uid']==1015 and not out['credentials_inherited'] and out['security']['CapEff']=='0000000000000000' and out['security']['NoNewPrivs']=='1' and out['root_write_blocked'] and b.returncode==0 and c.returncode==0 and s.returncode==0 and out['initialize']['passed']
print(json.dumps(out))
'''

def main():
    result={}
    for label,image in [('baseline','gpt2-codex-runtime:0.154.0'),('candidate','gpt2-codex-security:20261116-node22.23.5')]:
        p=subprocess.run(['sudo','docker','run','--rm','--network','none','--user','1015:1018',
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--security-opt','seccomp=/usr/local/libexec/gpt2-codex-seccomp.json',
            '--memory','768m','--memory-swap','768m','--cpus','0.5','--pids-limit','96',
            '--tmpfs','/tmp:rw,nosuid,nodev,size=128m',
            '--tmpfs','/probe-home:rw,nosuid,nodev,size=32m,uid=1015,gid=1018',
            '--entrypoint','python3',image,'-c',PROBE],
            text=True,capture_output=True,timeout=70,check=True)
        result[label]=json.loads(p.stdout)
    result['schema_unchanged']=result['baseline']['schema']==result['candidate']['schema']
    report={'checked_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'scope':'No-network containers, production seccomp/resource settings, no host mounts or credentials; no model turns',
            'probes':result}
    (ROOT/'probe-results-v3.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not all(result[label]['passed'] for label in ('baseline','candidate')) or not result['schema_unchanged']:
        raise SystemExit('Probe failed; candidate is not ready for promotion')

if __name__=='__main__':main()
