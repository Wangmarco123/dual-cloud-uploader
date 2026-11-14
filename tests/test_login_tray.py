import unittest
from unittest.mock import patch
from ali_qr import parse_authorize_url, authorization_completed, AuthorizationContinuation
from tray_support import TrayController
import cloud_uploader

URL = ("https://openapi.alipan.com/oauth/authorize?client_id=test&redirect_uri="
       "https%3A%2F%2Fapi.tickstep.com%2Fauth%2Ftickstep%2Faliyunpan%2Ftoken%2Fopenapi%2F"
       "test-ticket-123456%2Fauth2&scope=user:base")

class LoginWindowTests(unittest.TestCase):
    def test_both_login_buttons_launch_hidden_web_windows(self):
        for provider in ("ali","baidu"):
            with self.subTest(provider=provider), patch("cloud_uploader.subprocess.Popen") as popen:
                cloud_uploader.launch_login(provider)
                command=popen.call_args.args[0]
                self.assertIn("--qr",command)
                self.assertNotIn("--interactive",command)
                self.assertIn(provider,command)
    def test_authorization_url_returns_only_expected_ticket(self):
        self.assertEqual(parse_authorize_url("扫码\n"+URL+"\n"),(URL,"test-ticket-123456"))
    def test_untrusted_login_urls_are_not_opened(self):
        for value in (
            URL.replace("https://openapi.alipan.com","http://openapi.alipan.com"),
            URL.replace("openapi.alipan.com","openapi.alipan.com.evil.test"),
            URL.replace("api.tickstep.com","evil.test"),
            URL.replace("test-ticket-123456","..")):
            self.assertIsNone(parse_authorize_url(value))
    def test_completion_requires_exact_success_callback_and_ticket(self):
        url="https://api.tickstep.com/pages/tickstep/aliyunpan/oauth/openapi_login_result?status=success&ticketId=test-ticket-123456"
        self.assertTrue(authorization_completed(url,"test-ticket-123456"))
        for value in (url.replace("https:","http:"), url.replace("api.tickstep.com","evil.test"),
                      url.replace("success","failed"),url.replace("123456","654321"),
                      url+"&ticketId=other",url.replace("openapi_login_result","other")):
            self.assertFalse(authorization_completed(value,"test-ticket-123456"))

    def test_engine_resumes_once_only_after_matching_success_page(self):
        import io
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=None;process.stdin=io.StringIO()
        continuation=AuthorizationContinuation("test-ticket-123456")
        continuation.observe("https://openapi.alipan.com/oauth/authorize")
        self.assertFalse(continuation.resume(process))
        self.assertEqual(process.stdin.getvalue(),"")
        continuation.observe("https://api.tickstep.com/pages/tickstep/aliyunpan/oauth/openapi_login_result?status=success&ticketId=test-ticket-123456")
        self.assertTrue(continuation.resume(process))
        self.assertFalse(continuation.resume(process))
        self.assertEqual(process.stdin.getvalue(),"\n")

    def test_exited_engine_is_never_resumed(self):
        from unittest.mock import Mock
        process=Mock();process.poll.return_value=2
        continuation=AuthorizationContinuation("test-ticket-123456")
        continuation.completed.set()
        self.assertFalse(continuation.resume(process))
        process.stdin.write.assert_not_called()

class FakeRoot:
    hidden=False
    destroyed=False
    shown=False
    def withdraw(self):self.hidden=True
    def deiconify(self):self.hidden=False;self.shown=True
    def lift(self):pass
    def focus_force(self):pass

class FakeIcon:
    visible=False
    stopped=False
    def run_detached(self,setup):
        setup(self)
    def stop(self):
        self.stopped=True

class TrayTests(unittest.TestCase):
    def test_x_hides_without_stopping_or_destroying(self):
        root=FakeRoot();icon=FakeIcon()
        tray=TrayController(root,lambda:None,lambda:None,lambda *_:icon)
        tray.start()
        self.assertTrue(tray.hide())
        self.assertTrue(root.hidden)
        self.assertFalse(root.destroyed)
        self.assertFalse(icon.stopped)
    def test_tray_show_restores_window(self):
        root=FakeRoot();icon=FakeIcon()
        tray=TrayController(root,lambda:None,lambda:None,lambda *_:icon)
        tray.start();tray.hide();tray.show()
        self.assertTrue(root.shown)
        self.assertFalse(root.hidden)
    def test_icon_failure_keeps_window_reachable(self):
        def fail(*_):
            raise RuntimeError("tray unavailable")
        root=FakeRoot()
        tray=TrayController(root,lambda:None,lambda:None,fail)
        with self.assertRaises(RuntimeError):tray.start()
        self.assertFalse(tray.hide())
        self.assertFalse(root.hidden)

if __name__=="__main__":unittest.main()
