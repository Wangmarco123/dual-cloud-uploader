from http.cookies import SimpleCookie
import unittest
from baidu_qr import cookie_header, connect_cookie

class BaiduQRTests(unittest.TestCase):
    def test_only_baidu_cookies_are_imported(self):
        own=SimpleCookie()
        own["BDUSS"]="local-secret"
        own["BDUSS"]["domain"]=".baidu.com"
        foreign=SimpleCookie()
        foreign["AUTH"]="other-secret"
        foreign["AUTH"]["domain"]=".example.com"
        self.assertEqual(cookie_header([own,foreign]),"BDUSS=local-secret")
    def test_does_not_claim_login_without_bduss(self):
        cookie=SimpleCookie()
        cookie["BAIDUID"]="not-auth"
        cookie["BAIDUID"]["domain"]=".baidu.com"
        self.assertIsNone(cookie_header([cookie]))
    def test_transient_cookie_import_is_retried(self):
        class Event:
            def is_set(self):
                return False
            def wait(self, seconds):
                return False
        class Backend:
            calls = 0
            def run(self, arguments, **options):
                self.calls += 1
                if self.calls == 1:
                    raise RuntimeError("temporary network failure")
            def is_logged_in(self, cancelled):
                return True
        backend=Backend()
        self.assertTrue(connect_cookie(backend,"BDUSS=test-only",Event()))
        self.assertEqual(backend.calls,2)

    def test_lookalike_domains_are_rejected(self):
        cookie=SimpleCookie()
        cookie["BDUSS"]="bad"
        cookie["BDUSS"]["domain"]=".evilbaidu.com"
        self.assertIsNone(cookie_header([cookie]))

if __name__=="__main__":
    unittest.main()
