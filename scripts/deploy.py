"""Deploy committed runtime files through the dedicated restricted SSH key."""
import argparse,io,os,re,subprocess,sys,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--key',default=os.environ.get('ABS_DEPLOY_SSH_KEY'))
parser.add_argument('--known-hosts',default=str(ROOT/'deploy/known_hosts'))
parser.add_argument('--status',action='store_true')
args=parser.parse_args()
if not args.key:parser.error('Pass --key /path/to/abs_deploy, or set ABS_DEPLOY_SSH_KEY')
ssh=['ssh','-T','-i',str(Path(args.key).expanduser()),'-o','IdentitiesOnly=yes','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile='+str(Path(args.known_hosts).resolve()),'ubuntu@155.103.253.33']
if args.status:sys.exit(subprocess.run(ssh+['status']).returncode)
def git(*a):return subprocess.check_output(['git',*a],cwd=ROOT,text=True).strip()
if git('status','--porcelain'):raise SystemExit('Working tree must be clean. Commit and push your changes first.')
commit=git('rev-parse','HEAD')
if not re.fullmatch('[0-9a-f]{40}',commit):raise SystemExit('Invalid Git commit')
subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py'],cwd=ROOT,check=True)
subprocess.run(['node','tests/test_scoring.cjs'],cwd=ROOT,check=True)
subprocess.run(['node','tests/test_workspace.cjs'],cwd=ROOT,check=True)
names=[n for n in git('ls-tree','-r','--name-only',commit).splitlines() if re.fullmatch(r'app/[A-Za-z_][A-Za-z_0-9]*\.py',n) or n.startswith('app/static/abs/')]
required={'app/abs_api.py','app/abs_work.py'}|{'app/static/abs/'+n for n in ['index.html','workspace.js','workspace.css','scoring.js','catalog.json','tickets.js','tickets.css']}
if not required.issubset(names):raise SystemExit('Required runtime files missing')
with tempfile.TemporaryFile() as bundle:
    with tarfile.open(fileobj=bundle,mode='w:gz') as archive:
        for name in names:
            content=subprocess.check_output(['git','show',commit+':'+name],cwd=ROOT)
            info=tarfile.TarInfo(name);info.size=len(content);info.mode=0o644;archive.addfile(info,io.BytesIO(content))
    bundle.seek(0);subprocess.run(ssh+['deploy '+commit],stdin=bundle,check=True)
subprocess.run(['node','scripts/verify-deployment.cjs',commit],cwd=ROOT,check=True)
print('Deployed commit '+commit+' to https://zhikejulia.com/')
