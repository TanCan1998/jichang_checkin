import os
import base64
import unittest
from unittest.mock import MagicMock, patch

import requests
import main


class CheckinTests(unittest.TestCase):
    def test_cookie_config_does_not_require_password(self):
        with patch.dict(os.environ, {'URL': 'https://example.com', 'COOKIE': 'sid=one\nsid=two'}, clear=True):
            self.assertEqual(main.load_config(), ('https://example.com', [('', 'sid=one'), ('', 'sid=two')]))

    def test_cookie_mode_never_attempts_password_login(self):
        with patch.dict(os.environ, {'URL': 'https://example.com', 'COOKIE': 'sid=one'}, clear=True), patch.object(main, 'sign_with_cookie', return_value=True) as sign, patch.object(main, 'sign') as password_sign:
            self.assertEqual(main.main(), 0)
            sign.assert_called_once_with(1, 'https://example.com', 'sid=one')
            password_sign.assert_not_called()

    def test_cookie_success_and_expired_session(self):
        for result, expected in (({'ret': 1}, True), ({'ret': 0, 'msg': '未登录'}, False)):
            with self.subTest(result=result):
                session = MagicMock()
                session.__enter__.return_value = session
                session.post.return_value.json.return_value = result
                with patch.object(main, 'create_cookie_session', return_value=session), patch.object(main, 'notify'):
                    self.assertEqual(main.sign_with_cookie(1, 'https://example.com', 'sid=test'), expected)
                    self.assertEqual(session.headers.update.call_args.args[0]['Cookie'], 'sid=test')
                    self.assertEqual(session.post.call_args.args[0], 'https://example.com/user/checkin')

    def test_base64_login_page_and_hidden_tokens(self):
        html = '<input type="hidden" name="login_token" value="test"><meta name="csrf-token" content="csrf">'
        encoded = base64.b64encode(html.encode()).decode()
        form = main.LoginPage(main.decode_login_html(f'var originBody = "{encoded}";'))
        self.assertEqual(form.fields, {'login_token': 'test'})
        self.assertEqual(form.csrf, 'csrf')

    def test_current_phased_login_payload(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value.text = 'function buildLoginRequest() {}'
        session.post.side_effect = [MagicMock(json=lambda: {'ret': '1'}), MagicMock(json=lambda: {'ret': '1'})]
        with patch.object(main.requests, 'Session', return_value=session), patch.object(main, 'notify'):
            self.assertTrue(main.sign(1, 'https://example.com', 'a', 'p'))
            data = session.post.call_args_list[0].kwargs['data']
            self.assertEqual(data['phase'], 'password')
            self.assertEqual(data['host'], 'example.com')
            self.assertIsInstance(data['pageLoadedAt'], int)

    def test_invalid_config_fails_before_network(self):
        for env in ({}, {'URL': 'invalid'}, {'URL': 'https://example.com', 'CONFIG': 'one'}):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                self.assertEqual(main.main(), 1)

    def test_multiple_accounts_and_trailing_slash(self):
        with patch.dict(os.environ, {'URL': 'https://example.com/', 'CONFIG': 'a\np1\nb\np2'}):
            self.assertEqual(main.load_config(), ('https://example.com', [('a', 'p1'), ('b', 'p2')]))

    def test_all_accounts_attempted_and_failure_propagated(self):
        with patch.object(main, 'load_config', return_value=('https://example.com', [('a', 'p'), ('b', 'p')])), patch.object(main, 'sign', side_effect=[False, True]) as sign:
            self.assertEqual(main.main(), 1)
            self.assertEqual(sign.call_count, 2)

    def run_sign(self, login, result=None, error=None):
        session = MagicMock()
        session.__enter__.return_value = session
        session.get.return_value.text = ''
        if error:
            session.post.side_effect = error
        else:
            session.post.side_effect = [MagicMock(json=lambda: login), MagicMock(json=lambda: result)]
        captcha = dict.fromkeys(('lot_number', 'captcha_output', 'pass_token', 'gen_time'), 'test')
        with patch.object(main, 'solve_captcha', return_value=captcha), patch.object(main.requests, 'Session', return_value=session), patch.object(main, 'notify'):
            return main.sign(1, 'https://example.com', 'a', 'p'), session

    def test_success_without_captcha_uses_timeout(self):
        success, session = self.run_sign({'ret': 1}, {'ret': 1, 'msg': '成功'})
        self.assertTrue(success)
        self.assertEqual(session.post.call_count, 2)
        self.assertEqual(session.post.call_args_list[0].kwargs['data']['email'], 'a')
        self.assertEqual(session.post.call_args.kwargs['timeout'], 30)

    def test_already_signed_counts_as_success(self):
        success, _ = self.run_sign({'ret': 1}, {'ret': 0, 'msg': '您今天已经签到过了'})
        self.assertTrue(success)

    def test_captcha_challenge_uses_current_page_id(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.side_effect = [
            MagicMock(json=lambda: {'ret': 0, 'msg': '请完成验证码'}),
            MagicMock(json=lambda: {'ret': 1}),
            MagicMock(json=lambda: {'ret': 1}),
        ]
        session.get.return_value.text = 'captchaId: "' + 'a' * 32 + '"'
        captcha = dict.fromkeys(('lot_number', 'captcha_output', 'pass_token', 'gen_time'), 'test')
        with patch.object(main.requests, 'Session', return_value=session), patch.object(main, 'solve_captcha', return_value=captcha) as solve, patch.object(main, 'notify'):
            self.assertTrue(main.sign(1, 'https://example.com', 'a', 'p'))
            solve.assert_called_once_with('a' * 32)
            self.assertEqual(session.post.call_count, 3)
            self.assertIn('captcha_result[pass_token]', session.post.call_args_list[1].kwargs['data'])

    def test_captcha_failure_stops_login_retry(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value.json.return_value = {'ret': 0, 'msg': '验证码失败'}
        session.get.return_value.text = ''
        with patch.object(main.requests, 'Session', return_value=session), patch.object(main, 'solve_captcha', side_effect=RuntimeError()), patch.object(main, 'notify'):
            self.assertFalse(main.sign(1, 'https://example.com', 'a', 'p'))
            self.assertEqual(session.post.call_count, 1)

    def test_login_failure_does_not_attempt_checkin(self):
        success, session = self.run_sign({'ret': 0})
        self.assertFalse(success)
        self.assertEqual(session.post.call_count, 1)

    def test_checkin_rejection_fails(self):
        success, _ = self.run_sign({'ret': 1}, {'ret': 0, 'msg': '服务暂不可用'})
        self.assertFalse(success)

    def test_request_timeout_fails(self):
        success, _ = self.run_sign(None, error=requests.Timeout())
        self.assertFalse(success)

    def test_no_push_when_key_missing(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(main.requests, 'post') as post:
            main.notify('测试')
            post.assert_not_called()

    def test_notification_failure_does_not_raise(self):
        with patch.dict(os.environ, {'SCKEY': 'test'}), patch.object(main.requests, 'post', side_effect=requests.Timeout()):
            main.notify('测试')


if __name__ == '__main__':
    unittest.main()
