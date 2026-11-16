"""Build and test a private Caddy security candidate; never deploy it.

Run as ec2-user on the approved host. All downloads, caches, binaries and test
listeners remain under the fixed staging directory. No service changes occur.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tarfile
import time
import urllib.request

STAGE = Path('/home/ec2-user/chess-security-stage-20261115/caddy')
GO_VERSION = 'go1.27.4'
GO_ARCHIVE = GO_VERSION + '.linux-amd64.tar.gz'
GO_SHA256 = '7226736c2339719cda28fbf3a54d71aa63bcefe376e98cef00034268dab24840'
CADDY_VERSION = 'v2.11.9'

FIXTURE_GO = r'''package main
import (
 "bufio"; "compress/gzip"; "crypto/rand"; "crypto/rsa"; "crypto/sha1";
 "crypto/tls"; "crypto/x509"; "crypto/x509/pkix"; "encoding/base64";
 "encoding/json"; "encoding/pem"; "fmt"; "io"; "math/big"; "net";
 "net/http"; "net/http/httptest"; "os"; "os/exec"; "path/filepath";
 "strings"; "syscall"; "time"; "github.com/klauspost/compress/zstd"
)
func port() (int,error) { l,e:=net.Listen("tcp","127.0.0.1:0"); if e!=nil{return 0,e}; defer l.Close(); return l.Addr().(*net.TCPAddr).Port,nil }
func check(ok bool, message string) error {if !ok{return fmt.Errorf("%s",message)};return nil}
func run(binary,dir string, report map[string]any) error {
 key,e:=rsa.GenerateKey(rand.Reader,2048);if e!=nil{return e}
 cert:=&x509.Certificate{SerialNumber:big.NewInt(1),Subject:pkix.Name{CommonName:"isolated-caddy-test"},NotBefore:time.Now().Add(-time.Minute),NotAfter:time.Now().Add(time.Hour),IPAddresses:[]net.IP{net.ParseIP("127.0.0.1")},KeyUsage:x509.KeyUsageKeyEncipherment|x509.KeyUsageDigitalSignature,ExtKeyUsage:[]x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
 der,e:=x509.CreateCertificate(rand.Reader,cert,cert,&key.PublicKey,key);if e!=nil{return e}
 cp:=filepath.Join(dir,"test.crt");kp:=filepath.Join(dir,"test.key")
 crt:=pem.EncodeToMemory(&pem.Block{Type:"CERTIFICATE",Bytes:der})
 if e=os.WriteFile(cp,crt,0600);e!=nil{return e};if e=os.WriteFile(kp,pem.EncodeToMemory(&pem.Block{Type:"RSA PRIVATE KEY",Bytes:x509.MarshalPKCS1PrivateKey(key)}),0600);e!=nil{return e}
 upstream:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  switch r.URL.Path {
  case "/sse": w.Header().Set("Content-Type","text/event-stream");fmt.Fprint(w,"data: first\n\n");w.(http.Flusher).Flush();time.Sleep(30*time.Millisecond);fmt.Fprint(w,"data: second\n\n")
  case "/large":w.Header().Set("Content-Type","text/plain");fmt.Fprint(w,strings.Repeat("staging fixture ",200))
  case "/redirect":http.Redirect(w,r,"/health",http.StatusFound)
  case "/ws":
   conn,rw,err:=w.(http.Hijacker).Hijack();if err!=nil{return};defer conn.Close();conn.SetDeadline(time.Now().Add(5*time.Second))
   h:=sha1.Sum([]byte(r.Header.Get("Sec-WebSocket-Key")+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"))
   fmt.Fprintf(rw,"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n",base64.StdEncoding.EncodeToString(h[:]));rw.Flush()
   head:=make([]byte,2);if _,err=io.ReadFull(rw,head);err!=nil{return};n:=int(head[1]&127);if n>125||head[1]&128==0{return};mask:=make([]byte,4);io.ReadFull(rw,mask);p:=make([]byte,n);io.ReadFull(rw,p);for i:=range p{p[i]^=mask[i%4]};rw.Write(append([]byte{0x81,byte(n)},p...));rw.Flush()
  default:b,_:=io.ReadAll(io.LimitReader(r.Body,4096));w.Header().Set("Content-Type","application/json");json.NewEncoder(w).Encode(map[string]string{"path":r.URL.Path,"method":r.Method,"body":string(b),"proto":r.Header.Get("X-Forwarded-Proto"),"marker":r.Header.Get("X-Test-Marker")})
  }
 }));defer upstream.Close()
 hp,e:=port();if e!=nil{return e};tp,e:=port();if e!=nil{return e};if hp==tp{return fmt.Errorf("port collision; retry fixture")}
 caddyfile:=fmt.Sprintf(`{
 admin off
 auto_https off
 storage file_system { root %s }
 servers { protocols h1 h2 }
}
http://127.0.0.1:%d {
 encode zstd gzip
 reverse_proxy %s { flush_interval -1 }
}
https://127.0.0.1:%d {
 tls %s %s
 encode zstd gzip
 reverse_proxy %s { flush_interval -1 }
}
`,filepath.Join(dir,"data"),hp,strings.TrimPrefix(upstream.URL,"http://"),tp,cp,kp,strings.TrimPrefix(upstream.URL,"http://"))
 // Caddy block directives require newline-delimited inner directives.
 caddyfile=strings.ReplaceAll(caddyfile,"{ root ","{\n root ");caddyfile=strings.ReplaceAll(caddyfile,"{ protocols ","{\n protocols ");caddyfile=strings.ReplaceAll(caddyfile,"{ flush_interval ","{\n flush_interval ");caddyfile=strings.ReplaceAll(caddyfile," }","\n }")
 cfg:=filepath.Join(dir,"Caddyfile");if e=os.WriteFile(cfg,[]byte(caddyfile),0600);e!=nil{return e}
 validate:=exec.Command(binary,"validate","--config",cfg,"--adapter","caddyfile");v,e:=validate.CombinedOutput();os.WriteFile(filepath.Join(dir,"validate.log"),v,0600);if e!=nil{return fmt.Errorf("fixture validate: %w",e)};report["fixture_config_validated"]=true
 log,e:=os.OpenFile(filepath.Join(dir,"caddy.log"),os.O_CREATE|os.O_WRONLY|os.O_EXCL,0600);if e!=nil{return e};defer log.Close()
 child:=exec.Command(binary,"run","--config",cfg,"--adapter","caddyfile");child.Stdout=log;child.Stderr=log;if e=child.Start();e!=nil{return e}
 defer func(){child.Process.Signal(syscall.SIGINT);done:=make(chan error,1);go func(){done<-child.Wait()}();select{case <-done:case <-time.After(5*time.Second):child.Process.Kill();<-done};report["fixture_terminated"]=true}()
 plain:=&http.Client{Timeout:5*time.Second};base:=fmt.Sprintf("http://127.0.0.1:%d",hp)
 ready:=false;for i:=0;i<100;i++{r,err:=plain.Get(base+"/health");if err==nil{r.Body.Close();ready=r.StatusCode==200;if ready{break}};time.Sleep(50*time.Millisecond)};if !ready{return fmt.Errorf("fixture not ready")}
 req,_:=http.NewRequest("POST",base+"/echo",strings.NewReader("private-fixture-payload"));req.Header.Set("X-Test-Marker","preserved");resp,e:=plain.Do(req);if e!=nil{return e};var body map[string]string;e=json.NewDecoder(resp.Body).Decode(&body);resp.Body.Close();if e!=nil{return e};if e=check(resp.StatusCode==200&&body["method"]=="POST"&&body["body"]=="private-fixture-payload"&&body["marker"]=="preserved"&&body["proto"]=="http","HTTP1 forwarding mismatch");e!=nil{return e};report["http1_post_headers_body"]=true
 roots:=x509.NewCertPool();roots.AppendCertsFromPEM(crt);tr:=&http.Transport{TLSClientConfig:&tls.Config{RootCAs:roots},ForceAttemptHTTP2:true};defer tr.CloseIdleConnections();secure:=&http.Client{Transport:tr,Timeout:5*time.Second};tlsbase:=fmt.Sprintf("https://127.0.0.1:%d",tp)
 resp,e=secure.Get(tlsbase+"/health");if e!=nil{return e};body=map[string]string{};e=json.NewDecoder(resp.Body).Decode(&body);resp.Body.Close();if e!=nil{return e};if e=check(resp.StatusCode==200&&resp.ProtoMajor==2&&body["proto"]=="https","HTTP2/TLS forwarding mismatch");e!=nil{return e};report["http2_verified_tls"]=true
 tr1:=&http.Transport{TLSClientConfig:&tls.Config{RootCAs:roots},TLSNextProto:map[string]func(string,*tls.Conn)http.RoundTripper{}};defer tr1.CloseIdleConnections();resp,e=(&http.Client{Transport:tr1,Timeout:5*time.Second}).Get(tlsbase+"/health");if e!=nil{return e};resp.Body.Close();if e=check(resp.StatusCode==200&&resp.ProtoMajor==1,"TLS HTTP1 mismatch");e!=nil{return e};report["http1_verified_tls"]=true
 start:=time.Now();resp,e=secure.Get(tlsbase+"/sse");if e!=nil{return e};rd:=bufio.NewReader(resp.Body);first,e:=rd.ReadString('\n');elapsed:=time.Since(start);remaining,_:=io.ReadAll(rd);resp.Body.Close();if e!=nil{return e};if e=check(first=="data: first\n"&&strings.Contains(string(remaining),"data: second")&&elapsed<time.Second,"SSE streaming mismatch");e!=nil{return e};report["http2_sse_streaming"]=true
 req,_=http.NewRequest("GET",base+"/large",nil);req.Header.Set("Accept-Encoding","gzip");resp,e=plain.Do(req);if e!=nil{return e};if resp.Header.Get("Content-Encoding")!="gzip"{resp.Body.Close();return fmt.Errorf("gzip missing")};gz,e:=gzip.NewReader(resp.Body);if e!=nil{resp.Body.Close();return e};b,e:=io.ReadAll(gz);gz.Close();resp.Body.Close();if e!=nil{return e};if e=check(string(b)==strings.Repeat("staging fixture ",200),"gzip body mismatch");e!=nil{return e};report["gzip_response"]=true
 req,_=http.NewRequest("GET",base+"/large",nil);req.Header.Set("Accept-Encoding","zstd");resp,e=plain.Do(req);if e!=nil{return e};if resp.Header.Get("Content-Encoding")!="zstd"{resp.Body.Close();return fmt.Errorf("zstd missing")};zr,e:=zstd.NewReader(resp.Body);if e!=nil{resp.Body.Close();return e};b,e=io.ReadAll(zr);zr.Close();resp.Body.Close();if e!=nil{return e};if e=check(string(b)==strings.Repeat("staging fixture ",200),"zstd body mismatch");e!=nil{return e};report["zstd_response"]=true
 resp,e=plain.Get(base+"/redirect");if e!=nil{return e};resp.Body.Close();if e=check(resp.Request.URL.Path=="/health"&&resp.StatusCode==200,"redirect mismatch");e!=nil{return e};report["redirect"]=true
 conn,e:=net.DialTimeout("tcp",fmt.Sprintf("127.0.0.1:%d",hp),time.Second);if e!=nil{return e};defer conn.Close();conn.SetDeadline(time.Now().Add(5*time.Second));fmt.Fprintf(conn,"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Version: 13\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n",hp);br:=bufio.NewReader(conn);wr,e:=http.ReadResponse(br,&http.Request{Method:"GET"});if e!=nil{return e};if e=check(wr.StatusCode==101&&wr.Header.Get("Sec-WebSocket-Accept")=="s3pPLMBiTxaQ9kYGzzhZRbK+xOo=","WebSocket handshake mismatch");e!=nil{return e};payload:=[]byte("loopback echo");mask:=[]byte{1,2,3,4};frame:=[]byte{0x81,byte(len(payload))|128};frame=append(frame,mask...);for i,v:=range payload{frame=append(frame,v^mask[i%4])};conn.Write(frame);head:=make([]byte,2);if _,e=io.ReadFull(br,head);e!=nil{return e};reply:=make([]byte,int(head[1]&127));if _,e=io.ReadFull(br,reply);e!=nil{return e};if e=check(head[0]==0x81&&string(reply)==string(payload),"WebSocket echo mismatch");e!=nil{return e};report["websocket_echo"]=true
 report["loopback_http_port"]=hp;report["loopback_https_port"]=tp;report["automatic_https"]=false;report["production_changed"]=false;return nil
}
func main(){report:=map[string]any{};if len(os.Args)!=3{panic("binary and private test directory required")};err:=run(os.Args[1],os.Args[2],report);report["success"]=err==nil;if err!=nil{report["error"]=err.Error()};json.NewEncoder(os.Stdout).Encode(report);if err!=nil{os.Exit(1)}}
'''


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def prepare():
    if os.getuid() != 1000 or Path.home() != Path('/home/ec2-user'):
        raise RuntimeError('Run only as ec2-user, not root or a service account')
    STAGE.mkdir(mode=0o700, parents=True, exist_ok=True)
    if STAGE.resolve() != STAGE or STAGE.stat().st_uid != os.getuid():
        raise RuntimeError('Unexpected staging path or owner')
    for name in ('downloads', 'cache', 'gopath', 'bin', 'src', 'logs', 'home'):
        (STAGE / name).mkdir(mode=0o700, exist_ok=True)
    return {
        'PATH': str(STAGE / 'go/bin') + ':/usr/bin:/bin',
        'HOME': str(STAGE / 'home'), 'USER': 'ec2-user', 'LOGNAME': 'ec2-user',
        'GOROOT': str(STAGE / 'go'), 'GOPATH': str(STAGE / 'gopath'),
        'GOCACHE': str(STAGE / 'cache'), 'GOTOOLCHAIN': 'local',
        'GOSUMDB': 'sum.golang.org', 'GOPROXY': 'https://proxy.golang.org',
        'GOMAXPROCS': '2', 'GOMEMLIMIT': '2GiB', 'CGO_ENABLED': '0',
        'GOBIN': str(STAGE / 'bin'), 'GOFLAGS': '-p=2',
    }


def run(args, label, env, cwd=None, timeout=900):
    print('Running ' + label, flush=True)
    with (STAGE / 'logs' / (label + '.log')).open('wb') as log:
        result = subprocess.run(['nice', '-n', '10', *args], env=env,
                                cwd=cwd or STAGE, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(label + ' failed; inspect the private staging log')
    return (STAGE / 'logs' / (label + '.log')).read_text()


def build():
    env = prepare()
    archive = STAGE / 'downloads' / GO_ARCHIVE
    if not archive.exists():
        with urllib.request.urlopen('https://go.dev/dl/' + GO_ARCHIVE, timeout=60) as response:
            with archive.open('xb') as output:
                shutil.copyfileobj(response, output)
    if digest(archive) != GO_SHA256:
        raise RuntimeError('Go archive checksum mismatch')
    if not (STAGE / 'go/bin/go').exists():
        with tarfile.open(archive, 'r:gz') as source:
            for member in source.getmembers():
                target = (STAGE / member.name).resolve()
                if not str(target).startswith(str(STAGE / 'go') + '/') and target != STAGE / 'go':
                    raise RuntimeError('Archive path outside private Go directory')
                if member.issym() or member.islnk() or member.isdev():
                    raise RuntimeError('Unexpected archive link/device')
            source.extractall(STAGE)
    go = str(STAGE / 'go/bin/go')
    version = run([go, 'version'], 'go-version', env).strip()
    if version != 'go version go1.27.4 linux/amd64':
        raise RuntimeError('Wrong compiler version')
    src = STAGE / 'src'
    if not (src / 'go.mod').exists():
        run([go, 'mod', 'init', 'local/chess-security-caddy'], 'module-init', env, src)
    (src / 'main.go').write_text('''package main

import (
    caddycmd "github.com/caddyserver/caddy/v2/cmd"
    _ "github.com/caddyserver/caddy/v2/modules/standard"
)

func main() { caddycmd.Main() }
''')
    run([go, 'get', 'github.com/caddyserver/caddy/v2@' + CADDY_VERSION], 'caddy-module', env, src)
    # x/net 0.62 also covers the October HTML-parser fixes beyond 0.60's HTTP/2 fixes.
    run([go, 'get', 'golang.org/x/net@v0.62.0'], 'net-security-patch', env, src)
    # The first source scan found GO-2026-6865 in reachable zstd encoder paths.
    run([go, 'get', 'github.com/klauspost/compress@v1.20.4'], 'compress-security-patch', env, src)
    run([go, 'mod', 'tidy'], 'module-tidy', env, src)
    run([go, 'mod', 'verify'], 'module-verify', env, src)
    run([go, 'build', '-trimpath', '-ldflags=-s -w', '-o', str(STAGE / 'bin/caddy'), '.'],
        'caddy-build', env, src, timeout=1200)
    build_info = run([str(STAGE / 'bin/caddy'), 'build-info'], 'caddy-build-info', env)
    binary_version = run([str(STAGE / 'bin/caddy'), 'version'], 'caddy-version', env).strip()
    modules = run([go, 'list', '-m', '-json', 'all'], 'modules', env, src)
    report = {'stage': str(STAGE), 'go_version': version, 'go_archive_sha256': GO_SHA256,
              'caddy_version': binary_version, 'binary': str(STAGE / 'bin/caddy'),
              'binary_sha256': digest(STAGE / 'bin/caddy'), 'binary_size': (STAGE / 'bin/caddy').stat().st_size,
              'build_info': build_info, 'go_mod': (src / 'go.mod').read_text(),
              'go_sum_sha256': digest(src / 'go.sum'), 'module_verification': 'all modules verified',
              'build_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'production_changed': False}
    (STAGE / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key not in ('build_info','go_mod')}), flush=True)


def test():
    env = prepare()
    fixture = STAGE / ('fixture-' + time.strftime('%Y%m%dT%H%M%S', time.gmtime()))
    fixture.mkdir(mode=0o700)
    source = fixture / 'fixture.go'
    source.write_text(FIXTURE_GO)
    for key, sub in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'), ('XDG_CACHE_HOME', 'cache')]:
        env[key] = str(fixture / sub)
    output = run([str(STAGE / 'go/bin/go'), 'run', str(source), str(STAGE / 'bin/caddy'), str(fixture)],
                 'fixture-test', env, STAGE / 'src', timeout=120)
    result = json.loads(output)
    result['fixture'] = str(fixture)
    (STAGE / 'fixture-report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


def audit():
    env = prepare()
    go = str(STAGE / 'go/bin/go')
    run([go, 'install', 'golang.org/x/vuln/cmd/govulncheck@v1.9.0'], 'vuln-tool', env)
    command = [str(STAGE / 'bin/govulncheck'), '-json', './...']
    print('Running source vulnerability scan', flush=True)
    result = subprocess.run(['nice', '-n', '10', *command], env=env,
                            cwd=STAGE / 'src', capture_output=True, text=True, timeout=600)
    (STAGE / 'govulncheck.jsonl').write_text(result.stdout)
    (STAGE / 'logs/govulncheck.stderr').write_text(result.stderr)
    objects, offset = [], 0
    decoder = json.JSONDecoder()
    while offset < len(result.stdout):
        while offset < len(result.stdout) and result.stdout[offset].isspace():
            offset += 1
        if offset == len(result.stdout):
            break
        item, offset = decoder.raw_decode(result.stdout, offset)
        objects.append(item)
    findings = [x['finding'] for x in objects if 'finding' in x]
    report = {'tool_version': 'v1.9.0', 'command': command,
              'returncode': result.returncode, 'findings': findings,
              'config': next((x['config'] for x in objects if 'config' in x), {}),
              'advisory_ids': sorted({x['osv'] for x in findings}),
              'called_findings': [x for x in findings if any(t.get('function') for t in x.get('trace', []))],
              'imported_package_findings': [x for x in findings if any(t.get('package') for t in x.get('trace', []))]}
    (STAGE / 'vulnerability-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


def compare_live_config():
    """Read the live config and execute both adapters as astra, never provision."""
    if os.getuid() != 0 or STAGE.resolve() != STAGE:
        raise RuntimeError('Comparison needs root only for read-only file descriptors')
    account = pwd.getpwnam('astra')
    paths = [Path('/home/astra/.local/bin/caddy'),
             Path('/home/astra/.config/astra-chess/Caddyfile'),
             Path('/home/astra/.config/astra-chess/new-games.caddy')]
    def hashes():
        return {str(path): digest(path) for path in paths}
    def pids():
        return subprocess.check_output(['systemctl', 'show', 'astra-chess.service',
            'or-chess.service', 'astra-caddy.service', '-p', 'Id', '-p', 'MainPID'], text=True)
    before, pids_before = hashes(), pids()
    adapted, modules = {}, {}
    environment = {'PATH': '/usr/bin:/bin', 'HOME': '/nonexistent-caddy-security-stage',
        'USER': 'astra', 'LOGNAME': 'astra',
        'XDG_CONFIG_HOME': '/nonexistent-caddy-security-stage/config',
        'XDG_DATA_HOME': '/nonexistent-caddy-security-stage/data'}
    for name, binary in [('installed', paths[0]), ('candidate', STAGE / 'bin/caddy')]:
        descriptor = os.open(binary, os.O_RDONLY)
        try:
            for action, arguments in [('adapt', ['adapt', '--config', str(paths[1]), '--adapter', 'caddyfile']),
                                      ('modules', ['list-modules'])]:
                result = subprocess.run(['/proc/self/fd/' + str(descriptor), *arguments],
                    pass_fds=(descriptor,), user=account.pw_uid, group=account.pw_gid,
                    extra_groups=[], env=environment, cwd='/tmp', capture_output=True,
                    text=True, timeout=20, check=True)
                if action == 'adapt':
                    adapted[name] = json.loads(result.stdout)
                else:
                    modules[name] = sorted(line.strip() for line in result.stdout.splitlines()
                                           if line.strip() and 'modules:' not in line)
        finally:
            os.close(descriptor)
    report = {'adapted_as_user': 'astra', 'candidate_adapted_live_config': True,
        'adapted_config_equal': adapted['installed'] == adapted['candidate'],
        'installed_config_sha256': hashlib.sha256(json.dumps(adapted['installed'], sort_keys=True).encode()).hexdigest(),
        'candidate_config_sha256': hashlib.sha256(json.dumps(adapted['candidate'], sort_keys=True).encode()).hexdigest(),
        'installed_module_count': len(modules['installed']), 'candidate_module_count': len(modules['candidate']),
        'missing_modules': sorted(set(modules['installed']) - set(modules['candidate'])),
        'additional_modules': sorted(set(modules['candidate']) - set(modules['installed'])),
        'source_hashes_before': before, 'source_hashes_after': hashes(),
        'production_pids_before': pids_before, 'production_pids_after': pids(),
        'validation_limit': 'Live config adapted only, not provisioned/started. Private fixture separately tests provisioning and HTTP/TLS/proxy paths.'}
    report['production_unchanged'] = (report['source_hashes_before'] == report['source_hashes_after']
                                     and report['production_pids_before'] == report['production_pids_after'])
    output = STAGE / 'live-adapt-report.json'
    output.write_text(json.dumps(report, indent=2) + '\n')
    os.chown(output, 1000, 1000)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['build', 'test', 'audit', 'compare'])
    args = parser.parse_args()
    {'build': build, 'test': test, 'audit': audit, 'compare': compare_live_config}[args.action]()
