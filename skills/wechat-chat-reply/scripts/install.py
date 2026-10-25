"""Install the extracted skill folder, refusing to overwrite existing installations."""
import argparse,hashlib,json,pathlib,shutil

def main():
    p=argparse.ArgumentParser();p.add_argument('--skills-dir',type=pathlib.Path,default=pathlib.Path.home()/'.agents'/'skills');o=p.parse_args()
    source=pathlib.Path(__file__).resolve().parents[1];manifest=json.loads((source/'package-manifest.json').read_text(encoding='utf-8'))
    for rel,digest in manifest['files'].items():
        path=(source/rel).resolve()
        if not path.is_relative_to(source.resolve()):raise SystemExit('包内路径越界。')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise SystemExit('安装包校验失败：'+rel)
    destination=o.skills_dir.resolve()/'wechat-chat-reply'
    if destination.exists():raise SystemExit('目标已存在，未覆盖：'+str(destination))
    destination.parent.mkdir(parents=True,exist_ok=True);destination.mkdir()
    for rel in list(manifest['files'])+['package-manifest.json']:
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source/rel,target)
    print(json.dumps({'installed':str(destination),'next':'让 Codex 读取 SKILL.md 并运行 scripts/bootstrap.py，然后 doctor。未发现技能时重启 Codex。'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
