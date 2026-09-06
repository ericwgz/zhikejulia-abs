#!/usr/bin/env python3
"""Owner-installed SSH forced command. Repository deployments never replace it."""
import fcntl,gzip,hashlib,json,os,re,shlex,shutil,subprocess,sys,tarfile,tempfile,time,urllib.request
from pathlib import Path
BASE=Path('/opt/badrams/abs-api')
WEB_PARENT=Path('/opt/badrams/current/app/static').resolve()
WEB=WEB_PARENT/'abs'
ROOT_SCRIPT='/usr/local/sbin/abs-deploy-gateway.py'
MAX_BYTES=15*1024*1024

def run(*args):return subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout.strip()
def status():
    print(json.dumps({'service':run('systemctl','is-active','abs-api'),'release':os.readlink(BASE/'current'),'url':'https://zhikejulia.com/'},ensure_ascii=False),flush=True)
def verify():
    last=None
    for _ in range(12):
        try:
            with urllib.request.urlopen('http://127.0.0.1:8096/api/abs/health',timeout=3) as r:
                result=json.load(r)
                if result.get('ok') and result.get('catalogReady'):return
        except Exception as e:last=e
        time.sleep(.5)
    raise RuntimeError('Service health check failed') from last
def symlink(target,link):
    temp=link.with_name(link.name+'-deploy-tmp')
    if temp.is_symlink():temp.unlink()
    temp.symlink_to(target);os.replace(temp,link)
def deploy(commit):
    if WEB_PARENT.parent.parent.parent!=Path('/opt/badrams/releases'):raise RuntimeError('Unexpected web root')
    if not WEB.is_dir():raise RuntimeError('Current ABS static root missing')
    run('install','-d','-m','700','/opt/badrams/abs-deploy-incoming')
    with tempfile.TemporaryDirectory(prefix='upload-',dir='/opt/badrams/abs-deploy-incoming') as staging:
        stage=Path(staging);blob=stage/'runtime.tar.gz'
        with blob.open('wb') as f:
            size=0
            while chunk:=sys.stdin.buffer.read(65536):
                size+=len(chunk)
                if size>MAX_BYTES:raise RuntimeError('Release archive too large')
                f.write(chunk)
        expanded=stage/'runtime.tar'
        with gzip.open(blob,'rb') as src,expanded.open('wb') as out:
            unpacked=0
            while chunk:=src.read(65536):
                unpacked+=len(chunk)
                if unpacked>MAX_BYTES:raise RuntimeError('Expanded archive exceeds limits')
                out.write(chunk)
        content=stage/'content';content.mkdir();seen=set();total=0
        with tarfile.open(expanded,'r:') as archive:
            for entry in archive:
                name=entry.name;parts=Path(name).parts
                allowed=bool(re.fullmatch(r'app/[A-Za-z_][A-Za-z_0-9]*\.py',name) or re.fullmatch(r'app/static/abs/[A-Za-z0-9_./-]+\.(?:html|css|js|json|svg|png|jpg|webp|woff2)',name))
                if not allowed or not entry.isfile() or name in seen or '..' in parts or any(p.startswith('.') for p in parts):raise RuntimeError('Unsupported archive member')
                total+=entry.size
                if total>MAX_BYTES or len(seen)>=200:raise RuntimeError('Release exceeds limits')
                seen.add(name);dest=content/name;dest.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(entry) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
                os.chmod(dest,0o644)
        required={'app/abs_api.py','app/abs_work.py'}|{'app/static/abs/'+n for n in ['index.html','workspace.js','workspace.css','scoring.js','catalog.json','tickets.js','tickets.css']}
        if not required.issubset(seen):raise RuntimeError('Incomplete runtime archive')
        for path in (content/'app').glob('*.py'):compile(path.read_text(encoding='utf-8'),str(path),'exec')
        json.loads((content/'app/static/abs/catalog.json').read_text(encoding='utf-8'))
        stamp=time.strftime('%Y%m%dT%H%M%SZ',time.gmtime())+'-'+commit[:12]
        release=BASE/'releases'/stamp;release.mkdir(exist_ok=False)
        for path in (content/'app').glob('*.py'):shutil.copy2(path,release/path.name)
        (release/'REVISION').write_text(commit+'\n',encoding='utf-8')
        incoming=WEB_PARENT/('abs-new-'+stamp);shutil.copytree(content/'app/static/abs',incoming)
        for p in [incoming,*incoming.rglob('*')]:os.chmod(p,0o755 if p.is_dir() else 0o644)
        backup=Path('/opt/badrams/abs-backups')/stamp;backup.mkdir(exist_ok=False)
        old=os.readlink(BASE/'current');swapped=False
        (backup/'previous-api-link').write_text(old+'\n',encoding='utf-8')
        try:
            run('systemctl','stop','abs-api')
            WEB.rename(backup/'web');incoming.rename(WEB);swapped=True
            symlink(release,BASE/'current');run('systemctl','start','abs-api');verify();status()
            print(json.dumps({'deployedCommit':commit,'backup':str(backup)}),flush=True)
        except Exception:
            run('systemctl','stop','abs-api')
            if swapped:WEB.rename(backup/'failed-web')
            if (backup/'web').exists():(backup/'web').rename(WEB)
            symlink(old,BASE/'current');run('systemctl','start','abs-api');verify()
            raise

if __name__=='__main__':
    try:
        if os.geteuid()!=0:
            words=shlex.split(os.environ.get('SSH_ORIGINAL_COMMAND',''))
            if words==['status']:args=['status']
            elif len(words)==2 and words[0]=='deploy' and re.fullmatch('[0-9a-f]{40}',words[1]):args=words
            else:raise RuntimeError('Allowed commands: status, deploy <40-character Git SHA>')
            sys.exit(subprocess.run(['sudo','-n','/usr/bin/python3',ROOT_SCRIPT,'--root',*args]).returncode)
        if len(sys.argv)<3 or sys.argv[1]!='--root':raise RuntimeError('Use SSH gateway')
        with Path('/run/abs-deploy.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            if sys.argv[2:]==['status']:status()
            elif len(sys.argv)==4 and sys.argv[2]=='deploy' and re.fullmatch('[0-9a-f]{40}',sys.argv[3]):deploy(sys.argv[3])
            else:raise RuntimeError('Invalid command')
    except Exception as error:
        print(json.dumps({'error':str(error),'type':type(error).__name__}),file=sys.stderr);sys.exit(1)
