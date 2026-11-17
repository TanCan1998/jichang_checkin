import os
import unittest
from unittest.mock import MagicMock, patch

import requests
import main


class CheckinTests(unittest.TestCase):
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
