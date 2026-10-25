"""Portable, screenshot-free WeChat reply helper. All private state stays outside the skill."""
from __future__ import annotations
import argparse, contextlib, ctypes, datetime, hashlib, importlib.util, json, logging
import os, pathlib, re, struct, sys, tempfile, time, types, uuid
from ctypes import wintypes

SKILL = pathlib.Path(__file__).resolve().parents[1]
STATE = pathlib.Path(os.environ.get('WECHAT_REPLY_HOME') or pathlib.Path(os.environ.get('LOCALAPPDATA', pathlib.Path.home())) / 'CodexWechatReply')
UTC8 = datetime.timezone(datetime.timedelta(hours=8))

class Stop(RuntimeError): pass

def emit(value): print(json.dumps(value, ensure_ascii=False, indent=2), flush=True)
def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(temp, path)

def clean_name(value):
    return re.sub(r'(?:(?:长按|按住)鼠标\s*)?语音输入(?:文字)?$', '', value or '').strip()

def message_ref(msg):
    return {'local_id': msg['local_id'], 'shard': msg['shard'], 'sort_seq': msg['sort_seq']}

def sender_label(sender, me, peer):
    if sender == me: return 'self'
    if sender == peer: return 'peer'
    return 'unknown'

def exact_contact(contacts, name):
    matches = [c for c in contacts if name in (c.get('username'), c.get('remark'), c.get('nick_name'))]
    if len(matches) != 1:
        raise Stop('联系人必须精确且唯一；请使用完整备注或 username。候选：' + json.dumps(contacts, ensure_ascii=False))
    return matches[0]

def normalize_input(value):
    return re.sub(r'\[[^\[\]]{1,10}\]', '\uFFFC', value or '')

def approved_digest(ticket):
    fields = {k:ticket[k] for k in ('account', 'peer', 'display', 'content', 'reply_to', 'context_ref')}
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()

def validate_ticket(ticket, digest, now=None):
    if ticket.get('status') != 'prepared': raise Stop('该发送单已使用或结果未明，禁止重复发送。')
    if (time.time() if now is None else now) > ticket['expires_at']: raise Stop('发送单已过期，请重新读取消息并拟回复。')
    if digest != approved_digest(ticket) or digest != ticket.get('digest'): raise Stop('确认摘要不匹配，内容或目标已改变。')

class Backend:
    def __init__(self):
        if os.name != 'nt' or struct.calcsize('P') != 8:
            raise Stop('需要 Windows 和 64 位 Python 3.10+。')
        if sys.version_info < (3,10): raise Stop('需要 Python 3.10+。')
        source = SKILL / 'vendor' / 'wechatauto'
        manifest = json.loads((SKILL/'vendor'/'manifest.json').read_text(encoding='utf-8'))
        for name, digest in manifest['sha256'].items():
            if hashlib.sha256((source/name).read_bytes()).hexdigest() != digest:
                raise Stop('上游文件校验失败：' + name)
        # Do not import upstream __init__: it eagerly imports GUI/OCR/auto-login code.
        package = types.ModuleType('wechatauto'); package.__path__=[str(source)]
        sys.modules['wechatauto'] = package
        logger = types.ModuleType('wechatauto.logger'); logger.wxlog=logging.getLogger('wechat-chat-reply')
        sys.modules['wechatauto.logger'] = logger
        self.dbmod=self.load('db', source/'db.py')
        self.acc=self.load('accessibility', source/'accessibility.py')
        self.acc.GATE_CACHE_FILE=str(STATE/'gate-cache.json')
        self.auto=self.acc.auto
        self.process=self.discover()
    @staticmethod
    def load(name, path):
        fullname='wechatauto.'+name
        spec=importlib.util.spec_from_file_location(fullname, path)
        module=importlib.util.module_from_spec(spec);sys.modules[fullname]=module;spec.loader.exec_module(module)
        setattr(sys.modules['wechatauto'],name,module)
        return module
    def discover(self):
        import psutil
        found=[]
        for proc in psutil.process_iter(['pid','name','exe']):
            if (proc.info.get('name') or '').lower()!='weixin.exe': continue
            mod=self.acc.AccessibilityGate._weixin_dll_module(proc.pid)
            if not mod: continue
            handles=[]
            callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
            def visit(hwnd, _):
                pid=wintypes.DWORD();ctypes.windll.user32.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
                if pid.value==proc.pid and ctypes.windll.user32.IsWindowVisible(hwnd):
                    title=ctypes.create_unicode_buffer(1024);ctypes.windll.user32.GetWindowTextW(hwnd,title,len(title))
                    if title.value.strip() and ('微信' in title.value or 'Weixin' in title.value or 'WeChat' in title.value):handles.append(int(hwnd))
                return True
            callback=callback_type(visit)
            ctypes.windll.user32.EnumWindows(callback,0)
            if handles:found.append({'pid':proc.pid,'exe':proc.info['exe'],'dll':mod[2],'version':pathlib.Path(mod[2]).parent.name,'hwnds':handles})
        if len(found)!=1:raise Stop('需要唯一的已登录微信 4.x 主进程。请启动微信并完成登录；不要同时运行多个实例。')
        return found[0]
    def root(self):
        roots=[]
        if all(ctypes.windll.user32.IsIconic(wintypes.HWND(h)) for h in self.process['hwnds']):
            raise Stop('微信窗口已最小化，请先恢复到前台再读取界面或发送；数据库读取不受影响。')
        for hwnd in self.process['hwnds']:
            if ctypes.windll.user32.IsIconic(wintypes.HWND(hwnd)):continue
            c=self.auto.ControlFromHandle(hwnd)
            if any(True for _ in self.walk(c, lambda x:x.AutomationId=='chat_input_field', max_depth=25)): roots.append(c)
        if len(roots)!=1:raise Stop('未找到唯一的已登录聊天窗口；必要时先执行 activate。登录必须由本人完成。')
        return roots[0]
    def walk(self, control, predicate, depth=0, max_depth=25):
        if predicate(control):yield control
        if depth>=max_depth:return
        for child in control.GetChildren():yield from self.walk(child,predicate,depth+1,max_depth)
    def unique(self, root, predicate, label):
        found=list(self.walk(root,predicate))
        if len(found)!=1:raise Stop(label+'不唯一或不存在。')
        return found[0]
    def activate(self):
        gate=self.acc.AccessibilityGate
        # Never use wake(set_flag=True): it changes a system-wide screen-reader setting.
        audit=[]
        writer=gate._write_process_byte
        def checked(handle,address,value):
            before=gate._read_process_byte(handle,address)
            if before not in (0,1) or value not in (0,1):raise Stop('拒绝修改非布尔候选字节。')
            ok=writer(handle,address,value)
            after=gate._read_process_byte(handle,address)
            audit.append({'before':before,'after':after,'requested':value,'ok':bool(ok)})
            return ok and after==value
        gate._write_process_byte=staticmethod(checked)
        try:
            ok=False
            for hwnd in self.process['hwnds']:
                if gate._mmui_present(hwnd,timeout=.2) or gate._hot_activate_accessibility(hwnd,verify=True,max_candidates=4):ok=True;break
        finally:gate._write_process_byte=staticmethod(writer)
        if not ok:raise Stop('当前版本无障碍热激活失败。未启用系统读屏标志；不要声称原生转写已触发。')
        return {'activated':True,'version':self.process['version'],'writes':audit}
    def ui(self, contact=None):
        root=self.root();edit=self.unique(root,lambda c:c.AutomationId=='chat_input_field','聊天输入框')
        if contact and clean_name(edit.Name) not in {contact.get('remark'),contact.get('nick_name'),contact['username']}:
            raise Stop('当前窗口不是所选联系人。先打开正确会话。')
        lst=self.unique(root,lambda c:c.AutomationId=='chat_message_list','消息列表')
        return {'chat':clean_name(edit.Name),'rows':[{'class':c.ClassName,'text':c.Name,'sender':'unverified'} for c in lst.GetChildren()]}
    def input(self, contact):
        root=self.root();edit=self.unique(root,lambda c:c.AutomationId=='chat_input_field','聊天输入框')
        if clean_name(edit.Name) not in {contact.get('remark'),contact.get('nick_name'),contact['username']}:
            raise Stop('窗口会话与已确认联系人不一致，已停止。')
        return root,edit
    def open_chat(self, contact):
        root=self.root()
        try:self.input(contact);return {'opened':True,'already_open':True}
        except Stop:pass
        display=contact.get('remark') or contact.get('nick_name') or contact['username']
        search=self.unique(root,lambda c:c.ClassName=='mmui::XValidatorTextEdit' and c.Name=='搜索','搜索框')
        self.paste(search,display,clear=True)
        time.sleep(.6)
        results=list(self.walk(root,lambda c:any(part.startswith('search_item_') for part in c.AutomationId.split('.')) and (c.Name or '').split('\n')[0].strip()==display))
        if len(results)!=1:raise Stop('搜索结果不唯一或不可识别，未打开任何候选。请本人打开目标聊天后重试。')
        item=results[0]
        invoke=item.GetPattern(self.auto.PatternId.InvokePattern)
        if invoke:invoke.Invoke()
        else:
            select=item.GetPattern(self.auto.PatternId.SelectionItemPattern)
            if not select:raise Stop('搜索结果缺少可调用操作，请本人打开会话。')
            select.Select();item.SetFocus();self.auto.SendKeys('{Enter}')
        time.sleep(.4);self.input(contact)
        return {'opened':True,'contact':display}
    def paste(self, edit, text, clear=False):
        old=self.auto.GetClipboardText()
        try:
            if edit.SetFocus() is False:raise Stop('无法聚焦输入控件。')
            if clear:self.auto.SendKeys('{Ctrl}a')
            self.auto.SetClipboardText(text);self.auto.SendKeys('{Ctrl}v');time.sleep(.25)
        finally:self.auto.SetClipboardText(old)
    def send_approved(self, contact, content):
        root,edit=self.input(contact)
        value=edit.GetPattern(self.auto.PatternId.ValuePattern)
        if value is None:raise Stop('输入框不提供内容回读接口，禁止发送。')
        if value.Value:raise Stop('输入框已有草稿，未覆盖；请先处理草稿。')
        self.paste(edit,content)
        root,edit=self.input(contact)
        observed=edit.GetPattern(self.auto.PatternId.ValuePattern).Value
        if observed not in (content,normalize_input(content)):raise Stop('粘贴回读不一致，未按发送键；请检查草稿。')
        focused=self.auto.GetFocusedControl()
        if focused.AutomationId!='chat_input_field' or clean_name(focused.Name)!=clean_name(edit.Name):raise Stop('发送前焦点不在目标输入框，未发送。')
        # Exactly one Enter. No coordinate/OCR fallback and no automatic retry.
        self.auto.SendKeys('{Enter}')

@contextlib.contextmanager
def session(backend, options, media=False):
    module=backend.dbmod
    data=options.db_dir or module.auto_detect_db_dir()
    if not data:raise Stop('未自动找到微信数据目录，请用 --db-dir 指定含账号子目录的目录。')
    accounts=module._find_account_dirs(data)
    if options.account:
        accounts=[p for p in accounts if pathlib.Path(p).name==options.account]
    if len(accounts)!=1:raise Stop('账号必须唯一，请用 --account 指定目录名。候选：'+json.dumps([pathlib.Path(p).name for p in accounts],ensure_ascii=False))
    class Reader(module.WeChatDB):
        def _find_weixin_pids(self):return [backend.process['pid']]
        def _save_keys(self):pass
        def _collect_db_files(self):
            def wanted(path):
                p=pathlib.Path(path)
                return p.name=='contact.db' or (p.name.startswith('message_') and p.stem[8:].isdigit()) or (media and p.name.startswith('media_') and p.stem[6:].isdigit())
            return [(r,p,s) for r,p,s in super()._collect_db_files() if wanted(p)]
        def _load_or_extract_keys(self,master_key=None):
            self._keys.update(self.extract_keys())
            self.unkeyed=[r for r,p,s in self._db_files if not self._key_works(r)]
            if self.unkeyed:raise Stop('所选账号的必要数据库密钥不可用，未切换其他账号。')
    STATE.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='transient-db-',dir=STATE) as work:
        assert pathlib.Path(work).resolve().parent==STATE.resolve()
        db=Reader(db_dir=data,account=pathlib.Path(accounts[0]).name,workdir=work)
        try:yield db
        finally:db._keys.clear()

def context(db, name, limit=20):
    me=db.get_self_info()['username']
    contact=exact_contact(db.search_contact(name),name)
    if contact['username']==me:raise Stop('联系人解析为本人，已停止。')
    rows=db.get_messages(contact['username'],limit=limit)
    return me,contact,rows

def render(rows, me, peer):
    result=[]
    for row in reversed(rows):
        item=dict(row);item.pop('sender_id',None);sender=item.pop('sender_username','')
        item['sender']=sender_label(sender,me,peer)
        item['time']=datetime.datetime.fromtimestamp(item['create_time'],UTC8).isoformat()
        if item['type']!='文本':item['content']='['+item['type']+']'
        result.append(item)
    return result

def ticket_path(ticket_id):
    if not re.fullmatch(r'[a-f0-9]{32}',ticket_id):raise Stop('发送单标识无效。')
    return STATE/'tickets'/(ticket_id+'.json')

def command(options):
    b=Backend()
    if options.command=='doctor':
        data=options.db_dir or b.dbmod.auto_detect_db_dir()
        return {'python':sys.version.split()[0],'bits':64,'wechat':b.process,'db_dir':data,'accounts':[pathlib.Path(p).name for p in b.dbmod._find_account_dirs(data)] if data else [],'accessible':any(b.acc.AccessibilityGate._mmui_present(h,timeout=.2) for h in b.process['hwnds']),'state_dir':str(STATE)}
    if options.command=='activate':return b.activate()
    if options.command=='ui':return b.ui()
    if options.command=='send':return send_ticket(b,options)
    with session(b,options,media=options.command=='transcribe') as db:
        me,c,rows=context(db,options.contact,options.limit)
        if options.command=='read':return {'contact':c,'messages':render(rows,me,c['username'])}
        if options.command=='open':return b.open_chat(c)
        if options.command=='prepare':
            incoming=next((r for r in rows if r.get('sender_username')==c['username']),None)
            if not incoming:raise Stop('最近消息中没有已核实的对方消息。')
            text=pathlib.Path(options.content_file).read_text(encoding='utf-8-sig')
            if not text.strip() or any(ord(ch)<32 and ch not in '\n\r\t' for ch in text):raise Stop('待发送文本为空或含控制字符。')
            ticket={'account':db.account,'peer':c['username'],'display':c.get('remark') or c.get('nick_name') or c['username'],'content':text,'reply_to':message_ref(incoming),'context_ref':message_ref(rows[0]),'status':'prepared','created_at':time.time(),'expires_at':time.time()+1800}
            ticket['digest']=approved_digest(ticket);identifier=uuid.uuid4().hex
            save(ticket_path(identifier),ticket)
            return {'ticket':identifier,'digest':ticket['digest'],'recipient':ticket['display'],'content':text,'expires_in_seconds':1800,'sent':False}
        if options.command=='transcribe':return transcribe(b,db,c,rows,options)
        if options.command=='image':return read_image(b,db,c,rows,options)
    raise Stop('未知命令。')

def send_ticket(b,options):
    path=ticket_path(options.ticket)
    ticket=json.loads(path.read_text(encoding='utf-8'));validate_ticket(ticket,options.approved_digest)
    lock=path.with_suffix('.lock')
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    except FileExistsError:raise Stop('发送单已被占用，禁止并发发送。')
    try:
        ticket=json.loads(path.read_text(encoding='utf-8'));validate_ticket(ticket,options.approved_digest)
        with session(b,options) as db:
            if db.account!=ticket['account']:raise Stop('当前账号与确认时不同。')
            me,c,rows=context(db,ticket['peer'],30)
            if not rows or message_ref(rows[0])!=ticket['context_ref']:raise Stop('确认后聊天出现变化，请重新查看并确认回复。')
            baseline={(r['shard'],r['local_id']) for r in rows}
            ticket['status']='attempting';save(path,ticket)
            try:b.send_approved(c,ticket['content'])
            except Exception:
                ticket['status']='uncertain';save(path,ticket);raise
            deadline=time.monotonic()+10
            while True:
                current=db.get_messages(ticket['peer'],limit=15)
                matches=[r for r in current if (r['shard'],r['local_id']) not in baseline and r.get('sender_username')==me and r.get('content')==ticket['content']]
                if matches:
                    ticket['status']='sent';ticket['sent_message']=message_ref(matches[0]);save(path,ticket)
                    return {'sent':True,'recipient':ticket['display'],'content':ticket['content'],'database_verified':True}
                if time.monotonic()>=deadline:break
                time.sleep(1)
            ticket['status']='uncertain';save(path,ticket)
            raise Stop('发送键只按了一次，但数据库尚未确认。禁止自动重发；先核对聊天记录。')
    finally:
        os.close(fd);lock.unlink(missing_ok=True)

def select_image_message(rows, peer, message_id=None, shard=None):
    incoming=[r for r in rows if r.get('sender_username')==peer and r['type']=='图片']
    if message_id is not None:
        if not shard:raise Stop('--message-id 必须同时指定 --shard。')
        incoming=[r for r in incoming if r['local_id']==message_id and r['shard']==shard]
        if len(incoming)!=1:raise Stop('目标图片不唯一或不是对方发来的图片。')
    elif shard:raise Stop('--shard 必须同时指定 --message-id。')
    if not incoming:raise Stop('最近消息中没有已核实由对方发来的图片。')
    return incoming[0]

def read_image(b,db,contact,rows,options):
    message=select_image_message(rows,contact['username'],options.message_id,options.shard)
    b.load('media',SKILL/'vendor'/'wechatauto'/'media.py')
    from wechatauto.media import MediaDownloader,V2_MAGIC
    try:from PIL import Image
    except ImportError:raise Stop('图片依赖未安装，请重新运行 bootstrap.py。')
    row=db.get_message_row(contact['username'],message['local_id'],local_type=3,shard=message['shard'])
    base=MediaDownloader(db)
    digest=base._img_md5(row)
    if not digest:raise Stop('该图片消息缺少可定位的本地图片标识。')
    files=base._image_files(contact['username'],digest)
    if not files:raise Stop('图片尚未缓存到本机，请本人在微信打开该图片后重试；未截图。')
    probe=(files.get('thumb') or files.get('mid') or files.get('original'))[0]
    class TargetImage(MediaDownloader):
        def _probe_ct(self,dat_path=None):return super()._probe_ct(dat_path or probe)
        def _persist_key(self,key):pass
        def _scan_aes_key(self,monitor=False,monitor_timeout=0):return super()._scan_aes_key(monitor=False,monitor_timeout=0)
    out=STATE/'images'/uuid.uuid4().hex;out.mkdir(parents=True,exist_ok=True)
    media=TargetImage(db,save_dir=str(out))
    with open(probe,'rb') as file:encrypted_v2=file.read(6)==V2_MAGIC
    if encrypted_v2:
        cfg=db.extract_master_key()
        if cfg:db.cfg_dword=cfg[1];media._cfg_dword=cfg[1]
        # Do not call detect_image_key(): upstream may call missing _dbg_last_dat().
        key=media._derive_cfg_key()
        if not key:
            aes=media._scan_aes_key(monitor=False)
            key=(aes,media._install_xor_key()) if aes else None
        if not key:raise Stop('未取得该图片的可验证密钥，请本人打开微信图片大图后重试；未持续监听、未截图。')
        media._image_key=key[0];media._xor_key=key[1];media._img_key=key
    path=media.download_image(contact['username'],message['local_id'],tier=options.tier,shard=message['shard'])
    if not path:raise Stop('本机没有所需档位的图片，未改取其他档位。')
    with Image.open(path) as image:image.load();size=list(image.size);image_format=image.format
    stem=pathlib.Path(path).stem
    tier='original' if stem.endswith('_h') else 'thumb' if stem.endswith('_thumb') else 'mid'
    return {'message':message_ref(message),'sender':'peer','time':datetime.datetime.fromtimestamp(message['create_time'],UTC8).isoformat(),'path':path,'size':size,'format':image_format,'tier':tier,'screenshot_used':False,'keys_persisted':False}

def transcribe(b,db,contact,rows,options):
    incoming=[r for r in rows if r.get('sender_username')==contact['username'] and r['type']=='语音']
    if options.message_id is not None:
        if not options.shard:raise Stop('--message-id 必须同时指定 --shard。')
        incoming=[r for r in incoming if r['local_id']==options.message_id and r['shard']==options.shard]
    if not incoming:raise Stop('未找到已核实由对方发来的目标语音。')
    message=incoming[0]
    b.load('media',SKILL/'vendor'/'wechatauto'/'media.py')
    from wechatauto.media import MediaDownloader
    try:import pilk;from faster_whisper import WhisperModel
    except ImportError:raise Stop('语音依赖未安装，请运行 bootstrap.py --with-asr。')
    import wave
    with tempfile.TemporaryDirectory(prefix='transient-voice-',dir=STATE) as work:
        assert pathlib.Path(work).resolve().parent==STATE.resolve()
        media=MediaDownloader(db,save_dir=work)
        path=media.download_voice(contact['username'],message['local_id'],shard=message['shard'])
        if not path:raise Stop('原始语音尚未缓存到本机；请在微信播放一次后重试，或读取已完成的微信原生转写。')
        pcm=pathlib.Path(work)/'voice.pcm';wav=pathlib.Path(work)/'voice.wav'
        pilk.decode(path,str(pcm),pcm_rate=24000)
        with wave.open(str(wav),'wb') as f:f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(pcm.read_bytes())
        os.environ['HF_HUB_DISABLE_TELEMETRY']='1';os.environ['HF_HUB_DISABLE_XET']='1'
        os.environ['HF_HOME']=str(STATE/'model-cache')
        model=WhisperModel(options.model,device='cpu',compute_type='int8',cpu_threads=4,download_root=str(STATE/'models'))
        segments,info=model.transcribe(str(wav),language='zh',beam_size=5,vad_filter=False,condition_on_previous_text=False)
        segments=[{'text':s.text,'avg_logprob':s.avg_logprob,'no_speech_prob':s.no_speech_prob} for s in segments]
        low=not segments or any(s['avg_logprob'] < -1 or s['no_speech_prob']>.6 for s in segments)
        return {'message':message_ref(message),'sender':'peer','engine':'local-faster-whisper','model':options.model,'transcript':''.join(s['text'] for s in segments),'low_confidence':low,'segments':segments,'audio_uploaded':False}

def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='Screenshot-free WeChat 4.x reply helper')
    p.add_argument('--db-dir');p.add_argument('--account')
    sub=p.add_subparsers(dest='command',required=True)
    for name in ('doctor','activate','ui'):sub.add_parser(name)
    for name in ('read','open','prepare','transcribe','image'):
        s=sub.add_parser(name);s.add_argument('--contact',required=True);s.add_argument('--limit',type=int,default=20)
        if name=='prepare':s.add_argument('--content-file',required=True)
        if name in ('transcribe','image'):
            s.add_argument('--message-id',type=int);s.add_argument('--shard')
        if name=='transcribe':s.add_argument('--model',choices=['base','small'],default='small')
        if name=='image':s.add_argument('--tier',choices=['best','original','mid','thumb'],default='best')
    s=sub.add_parser('send');s.add_argument('--ticket',required=True);s.add_argument('--approved-digest',required=True)
    options=p.parse_args()
    try:emit(command(options))
    except Exception as e:
        emit({'ok':False,'error':str(e),'error_type':type(e).__name__});return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
