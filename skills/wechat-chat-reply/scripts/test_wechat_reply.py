"""Offline safety checks: no desktop input, network, or live message sending."""
import copy,importlib.util,pathlib,tempfile,time,types,unittest
from unittest.mock import Mock
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

if __name__=='__main__':unittest.main(verbosity=2)
