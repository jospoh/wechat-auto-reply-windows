"""Create an isolated Windows Python environment, never global site-packages."""
import argparse,json,os,pathlib,struct,subprocess,sys

def main():
    p=argparse.ArgumentParser();p.add_argument('--with-asr',action='store_true');p.add_argument('--wheelhouse');p.add_argument('--offline',action='store_true');o=p.parse_args()
    if os.name!='nt' or struct.calcsize('P')!=8 or sys.version_info<(3,10):raise SystemExit('需要 Windows / 64位 Python 3.10+。')
    skill=pathlib.Path(__file__).resolve().parents[1]
    state=pathlib.Path(os.environ.get('WECHAT_REPLY_HOME') or pathlib.Path(os.environ.get('LOCALAPPDATA',pathlib.Path.home()))/'CodexWechatReply')
    state.mkdir(parents=True,exist_ok=True);venv=state/'venv';python=venv/'Scripts'/'python.exe'
    if not python.exists():subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
    cmd=[str(python),'-m','pip','install','--disable-pip-version-check','--no-input','-r',str(skill/'scripts'/'requirements.txt')]
    if o.with_asr:cmd+=['-r',str(skill/'scripts'/'requirements-asr.txt')]
    if o.offline:cmd+=['--no-index']
    if o.wheelhouse:cmd+=['--find-links',o.wheelhouse]
    subprocess.run(cmd,check=True)
    subprocess.run([str(python),'-c','import uiautomation,numpy,cryptography,psutil,zstandard,PIL,imageio_ffmpeg'],check=True)
    if o.with_asr:subprocess.run([str(python),'-c','import pilk,faster_whisper'],check=True)
    print(json.dumps({'python':str(python),'helper':str(skill/'scripts'/'wechat_reply.py'),'state_dir':str(state),'asr_installed':o.with_asr,'model_downloaded':False},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
