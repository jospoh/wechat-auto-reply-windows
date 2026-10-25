"""Offline safety checks: no desktop input, network, or live message sending."""
import copy,importlib.util,pathlib,tempfile,time,types,unittest
from unittest.mock import Mock,patch
path=pathlib.Path(__file__).with_name('wechat_reply.py')
spec=importlib.util.spec_from_file_location('reply',path);reply=importlib.util.module_from_spec(spec);spec.loader.exec_module(reply)

class ContractTests(unittest.TestCase):
    def ticket(self):
        t={'account':'test_account','peer':'contact_test','display':'测试联系人','content':'你好','reply_to':{'shard':'a','local_id':1,'sort_seq':2},'context_ref':{'shard':'a','local_id':1,'sort_seq':2},'status':'prepared','expires_at':time.time()+60}
        t['digest']=reply.approved_digest(t);return t
    def test_sender_is_identity_not_position(self):
        self.assertEqual(reply.sender_label('me','me','peer'),'self')
        self.assertEqual(reply.sender_label('peer','me','peer'),'peer')
        self.assertEqual(reply.sender_label('','me','peer'),'unknown')
    def test_duplicate_contacts_fail(self):
        with self.assertRaises(reply.Stop):reply.exact_contact([{'username':'a','remark':'朋友'},{'username':'b','remark':'朋友'}],'朋友')
    def test_exact_id_resolves_duplicate_names(self):
        self.assertEqual(reply.exact_contact([{'username':'a','remark':'朋友'},{'username':'b','remark':'朋友'}],'b')['username'],'b')
    def test_unknown_sender_is_not_peer(self):
        row={'local_id':1,'shard':'s','sort_seq':2,'sender_username':'third','create_time':1,'type':'语音','content':'secret xml'}
        out=reply.render([row],'me','peer')[0]
        self.assertEqual(out['sender'],'unknown');self.assertEqual(out['content'],'[语音]')
    def test_approved_ticket_passes(self):
        t=self.ticket();reply.validate_ticket(t,t['digest'])
    def test_changed_text_or_target_fails(self):
        for field,value in [('content','different'),('peer','another')]:
            t=self.ticket();t[field]=value
            with self.assertRaises(reply.Stop):reply.validate_ticket(t,t['digest'])
    def test_expired_fails(self):
        t=self.ticket()
        with self.assertRaises(reply.Stop):reply.validate_ticket(t,t['digest'],now=t['expires_at']+1)
    def test_used_or_uncertain_cannot_retry(self):
        for status in ['sent','attempting','uncertain']:
            t=self.ticket();t['status']=status
            with self.assertRaises(reply.Stop):reply.validate_ticket(t,t['digest'])
    def test_ticket_path_cannot_escape(self):
        with self.assertRaises(reply.Stop):reply.ticket_path('../wrong')
    def test_chat_tail_cleanup(self):
        self.assertEqual(reply.clean_name('测试联系人长按鼠标 语音输入'),'测试联系人')
    def fake_backend(self,draft='',pasted='正确内容'):
        backend=reply.Backend.__new__(reply.Backend)
        value=types.SimpleNamespace(Value=draft)
        edit=Mock();edit.Name='测试联系人';edit.AutomationId='chat_input_field';edit.GetPattern.return_value=value
        backend.input=Mock(return_value=(None,edit))
        backend.auto=types.SimpleNamespace(PatternId=types.SimpleNamespace(ValuePattern=1),SendKeys=Mock(),GetFocusedControl=Mock(return_value=edit))
        def paste(*args,**kwargs):value.Value=pasted
        backend.paste=Mock(side_effect=paste)
        return backend
    def test_existing_draft_not_overwritten(self):
        b=self.fake_backend(draft='本人的未完成草稿')
        with self.assertRaises(reply.Stop):b.send_approved({},'正确内容')
        b.paste.assert_not_called();b.auto.SendKeys.assert_not_called()
    def test_bad_paste_never_presses_enter(self):
        b=self.fake_backend(pasted='错误内容')
        with self.assertRaises(reply.Stop):b.send_approved({},'正确内容')
        b.auto.SendKeys.assert_not_called()
    def test_verified_paste_sends_one_enter(self):
        b=self.fake_backend();b.send_approved({},'正确内容')
        b.auto.SendKeys.assert_called_once_with('{Enter}')
    def test_focus_changed_never_sends(self):
        b=self.fake_backend();b.auto.GetFocusedControl.return_value=types.SimpleNamespace(AutomationId='other',Name='other')
        with self.assertRaises(reply.Stop):b.send_approved({},'正确内容')
        b.auto.SendKeys.assert_not_called()

    def image_rows(self):
        return [{'local_id':7,'shard':'s1','sort_seq':3,'sender_username':'me','type':'图片'}, {'local_id':7,'shard':'s2','sort_seq':2,'sender_username':'peer','type':'图片'}, {'local_id':6,'shard':'s1','sort_seq':1,'sender_username':'unknown','type':'图片'}]
    def test_image_chooses_peer_not_latest_self(self):
        self.assertEqual(reply.select_image_message(self.image_rows(),'peer')['shard'],'s2')
    def test_image_id_requires_shard(self):
        with self.assertRaises(reply.Stop):reply.select_image_message(self.image_rows(),'peer',7)
    def test_image_rejects_other_shard_same_id(self):
        with self.assertRaises(reply.Stop):reply.select_image_message(self.image_rows(),'peer',7,'s1')
    def test_image_rejects_unknown_sender(self):
        with self.assertRaises(reply.Stop):reply.select_image_message(self.image_rows(),'peer',6,'s1')

class WindowTests(unittest.TestCase):
    def record(self, hwnd=101, visible=False, minimized=False, **kw):
        r={'hwnd':hwnd,'pid':11,'title':'微信','class':'Qt51514QWindowIcon','visible':visible,'minimized':minimized,'owner':0,'style':0}
        r.update(kw);return r
    def backend(self, records=None, roles=None):
        b=reply.Backend.__new__(reply.Backend);b.process={'pid':11,'hwnds':[]}
        b._window_records=Mock(return_value=records or [])
        b.auto=types.SimpleNamespace(ControlFromHandle=lambda h:types.SimpleNamespace(ClassName=(roles or {}).get(h,'Qt51514QWindowIcon'),GetChildren=lambda:[object()]))
        b.acc=types.SimpleNamespace(AccessibilityGate=types.SimpleNamespace(_weixin_dll_module=Mock(return_value=(1,2,'C:/Weixin/4.1.15.56/Weixin.dll'))))
        return b
    def processes(self, count=1, name='Weixin.exe'):
        return [types.SimpleNamespace(pid=11+i,info={'pid':11+i,'name':name,'exe':'C:/Weixin/Weixin.exe'}) for i in range(count)]
    def discover(self,b,processes):
        fake=types.SimpleNamespace(process_iter=lambda fields:processes,Error=OSError)
        with patch.dict(reply.sys.modules,{'psutil':fake}):return b.discover()
    def test_hidden_window_does_not_mean_process_missing(self):
        b=self.backend([self.record()]);result=self.discover(b,self.processes())
        self.assertEqual(result['pid'],11);self.assertEqual(result['hwnds'],[101])
    def test_running_process_without_window_is_retained(self):
        b=self.backend();self.assertEqual(self.discover(b,self.processes())['hwnds'],[])
    def test_no_process_has_distinct_error(self):
        with self.assertRaisesRegex(reply.Stop,'进程未运行'):self.discover(self.backend(),[])
    def test_module_access_error_does_not_claim_not_running(self):
        b=self.backend();b.acc.AccessibilityGate._weixin_dll_module.return_value=None
        with self.assertRaisesRegex(reply.Stop,'已检测到微信进程'):self.discover(b,self.processes())
    def test_hidden_second_instance_is_not_silently_ignored(self):
        b=self.backend([self.record()])
        with self.assertRaisesRegex(reply.Stop,'多个微信主进程'):self.discover(b,self.processes(2))
    def test_miniprogram_process_is_not_main_wechat(self):
        procs=self.processes()+self.processes(name='WeChatAppEx.exe');b=self.backend([self.record()])
        self.assertEqual(self.discover(b,procs)['pid'],11)
        b.acc.AccessibilityGate._weixin_dll_module.assert_called_once_with(11)
    def test_tray_hidden_is_not_iconic(self):
        b=self.backend([self.record(visible=False,minimized=False)],{101:'mmui::MainWindow'})
        self.assertEqual(b.window_status()['state'],'hidden')
    def test_taskbar_minimized_has_own_state(self):
        b=self.backend([self.record(visible=True,minimized=True)],{101:'mmui::MainWindow'})
        self.assertEqual(b.window_status()['state'],'minimized')
    def test_semantic_main_role_wins_over_visible_auxiliary(self):
        b=self.backend([self.record(),self.record(102,visible=True,title='Weixin')],{101:'mmui::MainWindow',102:'QWidget'})
        self.assertEqual(b.window_status()['main_hwnd'],101)
    def test_two_semantic_main_windows_remain_ambiguous(self):
        b=self.backend([self.record(),self.record(102)],{101:'mmui::MainWindow',102:'mmui::MainWindow'})
        self.assertIsNone(b.window_status()['main_hwnd'])
    def test_child_and_tray_helper_are_not_candidates(self):
        rows=[self.record(),self.record(102,style=0x40000000),self.record(103,title='WxTrayIconMessageWindow',**{'class':'Qt51514WxTrayIconMessageWindowClass'})]
        self.assertEqual([r['hwnd'] for r in reply.Backend._window_candidates(rows)],[101])
    def test_root_restores_hidden_window_before_reading(self):
        b=self.backend();b.window_status=Mock(side_effect=[{'state':'hidden','main_hwnd':101},{'state':'visible','main_hwnd':101}]);b.restore=Mock()
        b.walk=Mock(return_value=iter([object()]))
        b.root();b.restore.assert_called_once()
    def test_visible_root_does_not_restore(self):
        b=self.backend();b.window_status=Mock(return_value={'state':'visible','main_hwnd':101});b.restore=Mock();b.walk=Mock(return_value=iter([object()]))
        b.root();b.restore.assert_not_called()
    def test_restore_checks_result_and_never_starts_process(self):
        b=self.backend(roles={101:'mmui::MainWindow'});b.window_status=Mock(side_effect=[{'state':'hidden','main_hwnd':101},{'state':'visible','main_hwnd':101}]);b._restore_window=Mock(return_value=True);b._open_from_tray=Mock()
        result=b.restore();b._open_from_tray.assert_called_once();b._restore_window.assert_called_once_with(101);self.assertFalse(result['new_process_started'])
    def test_missing_window_does_not_restore_auxiliary(self):
        b=self.backend();b.window_status=Mock(return_value={'state':'missing','main_hwnd':None});b._restore_window=Mock()
        with self.assertRaisesRegex(reply.Stop,'进程已运行'):b.restore()
        b._restore_window.assert_not_called()

    def test_root_accepts_search_without_chat_input(self):
        b=self.backend();b.window_status=Mock(return_value={'state':'visible','main_hwnd':101})
        search=types.SimpleNamespace(AutomationId='search',Name='搜索')
        root=types.SimpleNamespace(GetChildren=lambda:[search])
        b.auto.ControlFromHandle=Mock(return_value=root)
        self.assertIs(b.root(),root)

    def test_empty_main_tree_has_bounded_failure(self):
        b=self.backend();b.window_status=Mock(return_value={'state':'visible','main_hwnd':101})
        b.auto.ControlFromHandle=Mock(return_value=types.SimpleNamespace(GetChildren=lambda:[]))
        with patch.object(reply.time,'monotonic',side_effect=[0,4]):
            with self.assertRaisesRegex(reply.Stop,'主窗口子控件'):b.root()

class TrayTests(unittest.TestCase):
    def control(self,name='',kind='ButtonControl',aid='',children=(),cls='',offscreen=False):
        c=Mock();c.Name=name;c.ControlTypeName=kind;c.AutomationId=aid;c.ClassName=cls;c.IsOffscreen=offscreen;c.GetChildren.return_value=list(children)
        return c
    def backend(self):
        b=reply.Backend.__new__(reply.Backend);b.process={'pid':11};b._tray_controls=Mock()
        return b
    def test_visible_icon_double_clicked_without_expand(self):
        b=self.backend();icon=self.control('微信');b._tray_controls.return_value=[icon]
        b._open_from_tray();icon.DoubleClick.assert_called_once_with(simulateMove=False)
    def test_hidden_icon_expands_and_reenumerates(self):
        b=self.backend();expand=self.control(aid='1502');icon=self.control('微信')
        b._tray_controls.side_effect=[[expand],[icon]]
        b._open_from_tray();expand.Click.assert_called_once_with(simulateMove=False);icon.DoubleClick.assert_called_once_with(simulateMove=False)
        self.assertEqual(b._tray_controls.call_count,2)
    def test_duplicate_icons_never_clicked(self):
        b=self.backend();icons=[self.control('微信'),self.control('Weixin')];b._tray_controls.return_value=icons
        with self.assertRaisesRegex(reply.Stop,'不唯一'):b._open_from_tray()
        for icon in icons:icon.DoubleClick.assert_not_called()
    def test_missing_or_duplicate_expand_never_clicked(self):
        for count in (0,2):
            b=self.backend();buttons=[self.control(aid='1502') for _ in range(count)];b._tray_controls.return_value=buttons
            with self.assertRaisesRegex(reply.Stop,'未找到唯一'):b._open_from_tray()
            for button in buttons:button.Click.assert_not_called()
    def test_offscreen_icon_is_not_clicked(self):
        b=self.backend();icon=self.control('微信',offscreen=True);b._tray_controls.return_value=[icon]
        with self.assertRaises(reply.Stop):b._open_from_tray()
        icon.DoubleClick.assert_not_called()
    def test_expanded_tray_timeout_is_bounded(self):
        b=self.backend();expand=self.control(aid='1502');b._tray_controls.return_value=[expand]
        with patch.object(reply.time,'monotonic',side_effect=[0,4]):
            with self.assertRaisesRegex(reply.Stop,'展开托盘后'):b._open_from_tray()
    def test_discovery_excludes_application_content(self):
        b=reply.Backend.__new__(reply.Backend)
        fake_icon=self.control('微信');app=self.control(children=[fake_icon],cls='ApplicationWindow')
        real_icon=self.control('微信');tray=self.control(children=[real_icon],cls='NotifyIconOverflowWindow')
        b._notification_handles=Mock(return_value=[11,12])
        b.auto=types.SimpleNamespace(ControlFromHandle=lambda h:{11:app,12:tray}[h],GetRootControl=Mock(side_effect=AssertionError('Desktop UIA enumeration is forbidden')))
        self.assertEqual(b._tray_controls(),[tray,real_icon])
    def restore_backend(self,before,after,children=True):
        b=self.backend();b.window_status=Mock(side_effect=[before,after]);b._open_from_tray=Mock();b._restore_window=Mock(return_value=True)
        b.auto=types.SimpleNamespace(ControlFromHandle=lambda h:types.SimpleNamespace(ClassName='mmui::MainWindow',GetChildren=lambda:[object()] if children else []))
        return b
    def test_ambiguous_hidden_handles_use_tray_not_guessed_handle(self):
        b=self.restore_backend({'state':'ambiguous','main_hwnd':None},{'state':'visible','main_hwnd':101})
        self.assertEqual(b.restore()['method'],'tray_double_click');b._open_from_tray.assert_called_once();b._restore_window.assert_called_once_with(101)
    def test_visible_blank_window_uses_tray_and_requires_readiness(self):
        b=self.restore_backend({'state':'visible','main_hwnd':101},{'state':'visible','main_hwnd':101})
        b._ready_window=Mock(side_effect=[False,True])
        self.assertTrue(b.restore()['uia_tree_available']);b._open_from_tray.assert_called_once()
    def test_blank_after_tray_never_reports_success(self):
        status={'state':'visible','main_hwnd':101};b=self.restore_backend(status,status,children=False)
        with patch.object(reply.time,'monotonic',side_effect=[0,6]):
            with self.assertRaisesRegex(reply.Stop,'空白窗口'):b.restore()
        b._restore_window.assert_not_called()
    def test_minimized_window_uses_native_restore(self):
        b=self.restore_backend({'state':'minimized','main_hwnd':101},{'state':'visible','main_hwnd':101})
        self.assertEqual(b.restore()['method'],'native_minimized');b._open_from_tray.assert_not_called()
    def test_login_window_is_not_automated(self):
        b=self.backend();b.window_status=Mock(return_value={'state':'visible','main_hwnd':101,'logged_in':False});b._open_from_tray=Mock()
        with self.assertRaisesRegex(reply.Stop,'本人完成登录'):b.restore()
        b._open_from_tray.assert_not_called()
    def test_root_recovers_blank_or_ambiguous_window(self):
        for status in ({'state':'ambiguous','main_hwnd':None},{'state':'visible','main_hwnd':101,'uia_tree_available':False}):
            b=self.restore_backend(status,{'state':'visible','main_hwnd':101});b.restore=Mock()
            self.assertIsNotNone(b.root());b.restore.assert_called_once()

class NavigationTests(unittest.TestCase):
    contact={'username':'peer','nick_name':'目标联系人','remark':''}
    def backend(self,results=1):
        b=reply.Backend.__new__(reply.Backend)
        root=object();b.root=Mock(return_value=root)
        b.input=Mock(side_effect=[reply.Stop('没有聊天输入框'),(root,object())])
        b.window_status=Mock(return_value={'main_hwnd':101});b._restore_window=Mock()
        search=types.SimpleNamespace(ClassName='mmui::XValidatorTextEdit',Name='搜索')
        b.unique=Mock(return_value=search);b.paste=Mock()
        candidates=[Mock(AutomationId='search_item_'+str(i)) for i in range(results)]
        for item in candidates:item.Name='目标联系人\n联系人'
        b.walk=Mock(side_effect=lambda root,predicate:iter(c for c in candidates if predicate(c)))
        return b,search,candidates
    def test_no_chat_searches_then_verifies_selected_contact(self):
        b,search,candidates=self.backend()
        with patch.object(reply.time,'sleep'):result=b.open_chat(self.contact)
        self.assertTrue(result['opened'])
        b.paste.assert_called_once_with(search,'目标联系人',clear=True)
        candidates[0].Click.assert_called_once_with(simulateMove=False)
        self.assertEqual(b.input.call_args_list,[unittest.mock.call(self.contact)]*2)
    def test_correct_chat_skips_search(self):
        b,search,candidates=self.backend();b.input.side_effect=None
        result=b.open_chat(self.contact)
        self.assertTrue(result['already_open']);b.paste.assert_not_called()
    def test_ambiguous_or_missing_result_never_selects(self):
        for count in (0,2):
            with self.subTest(count=count):
                b,search,candidates=self.backend(count)
                with patch.object(reply.time,'sleep'):
                    with self.assertRaisesRegex(reply.Stop,'搜索结果不唯一'):b.open_chat(self.contact)
                for item in candidates:item.Click.assert_not_called()
    def test_send_navigation_failure_keeps_ticket_prepared(self):
        ticket=ContractTests().ticket()
        row=dict(ticket['context_ref'],sender_username='peer')
        b=Mock();b.open_chat.side_effect=reply.Stop('搜索结果不唯一')
        db=Mock(account='test_account')
        with tempfile.TemporaryDirectory() as folder:
            target=pathlib.Path(folder)/'ticket.json';reply.save(target,ticket)
            options=types.SimpleNamespace(ticket='unused',approved_digest=ticket['digest'])
            cm=unittest.mock.MagicMock();cm.__enter__.return_value=db
            with patch.object(reply,'ticket_path',return_value=target),patch.object(reply,'session',return_value=cm),patch.object(reply,'context',return_value=('me',self.contact,[row])):
                with self.assertRaisesRegex(reply.Stop,'搜索结果不唯一'):reply.send_ticket(b,options)
            self.assertEqual(reply.json.loads(target.read_text(encoding='utf-8'))['status'],'prepared')
            b.send_approved.assert_not_called()
    def test_send_opens_chat_before_attempt_and_verifies_database(self):
        ticket=ContractTests().ticket();row=dict(ticket['context_ref'],sender_username='peer')
        b=Mock();db=Mock(account='test_account')
        db.get_messages.return_value=[dict(row,local_id=2,sender_username='me',content=ticket['content'])]
        with tempfile.TemporaryDirectory() as folder:
            target=pathlib.Path(folder)/'ticket.json';reply.save(target,ticket)
            def status():return reply.json.loads(target.read_text(encoding='utf-8'))['status']
            def opened(contact):self.assertEqual(status(),'prepared')
            def sent(contact,content):self.assertEqual(status(),'attempting')
            b.open_chat.side_effect=opened;b.send_approved.side_effect=sent
            options=types.SimpleNamespace(ticket='unused',approved_digest=ticket['digest'])
            cm=unittest.mock.MagicMock();cm.__enter__.return_value=db
            with patch.object(reply,'ticket_path',return_value=target),patch.object(reply,'session',return_value=cm),patch.object(reply,'context',return_value=('me',self.contact,[row])):
                result=reply.send_ticket(b,options)
            self.assertTrue(result['sent']);self.assertTrue(result['database_verified'])
            self.assertEqual(b.method_calls,[unittest.mock.call.open_chat(self.contact),unittest.mock.call.send_approved(self.contact,ticket['content'])])

class FocusTests(unittest.TestCase):
    def test_wrong_focus_does_not_type_or_replace_clipboard(self):
        b=reply.Backend.__new__(reply.Backend)
        target=Mock();target.GetRuntimeId.return_value=[1,2]
        focused=Mock();focused.GetRuntimeId.return_value=[1,3]
        b.auto=Mock();b.auto.GetFocusedControl.return_value=focused
        b.auto.GetClipboardText.return_value='original'
        with self.assertRaisesRegex(reply.Stop,'实际焦点'):
            b.paste(target,'contact',clear=True)
        b.auto.SendKeys.assert_not_called()
        b.auto.SetClipboardText.assert_called_once_with('original')
    def test_focus_change_after_select_all_prevents_paste(self):
        b=reply.Backend.__new__(reply.Backend)
        target=Mock();target.GetRuntimeId.return_value=[1,2]
        wrong=Mock();wrong.GetRuntimeId.return_value=[1,3]
        b.auto=Mock();b.auto.GetFocusedControl.side_effect=[target,wrong]
        with self.assertRaisesRegex(reply.Stop,'实际焦点'):
            b.paste(target,'contact',clear=True)
        b.auto.SendKeys.assert_called_once_with('{Ctrl}a')

if __name__=='__main__':unittest.main(verbosity=2)
