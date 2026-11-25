import os
import unittest
from unittest.mock import MagicMock, patch

import requests
import main


class CheckinTests(unittest.TestCase):
    def test_cookie_config_and_trailing_slash(self):
        with patch.dict(os.environ, {'URL': 'https://example.com/', 'COOKIE': 'sid=one\nsid=two'}, clear=True):
            self.assertEqual(main.load_config(), ('https://example.com', ['sid=one', 'sid=two']))

    def test_invalid_config_fails_before_network(self):
        for env in (
            {},
            {'URL': 'invalid', 'COOKIE': 'sid=test'},
            {'URL': 'https://example.com'},
            {'URL': 'https://example.com', 'COOKIE': 'sid=one\n\nsid=two'},
            {'URL': 'https://example.com', 'COOKIE': 'invalid'},
        ):
            with self.subTest(env=env), patch.dict(os.environ, env, clear=True):
                self.assertEqual(main.main(), 1)

    def test_all_cookies_attempted_and_failure_propagated(self):
        with patch.object(main, 'load_config', return_value=('https://example.com', ['sid=one', 'sid=two'])), \
                patch.object(main, 'sign_with_cookie', side_effect=[False, True]) as sign:
            self.assertEqual(main.main(), 1)
            self.assertEqual(sign.call_count, 2)

    def test_cookie_checkin_results(self):
        for result, expected in (
            ({'ret': 1}, True),
            ({'ret': 0, 'msg': '您今天已经签到过了'}, True),
            ({'ret': 0, 'msg': '未登录'}, False),
        ):
            with self.subTest(result=result):
                session = MagicMock()
                session.__enter__.return_value = session
                session.post.return_value.json.return_value = result
                with patch.object(main, 'create_cookie_session', return_value=session), patch.object(main, 'notify'):
                    self.assertEqual(main.sign_with_cookie(1, 'https://example.com', 'sid=test'), expected)
                    self.assertEqual(session.headers.update.call_args.args[0]['Cookie'], 'sid=test')
                    self.assertEqual(session.post.call_args.args[0], 'https://example.com/user/checkin')

    def test_cookie_request_timeout_fails(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.side_effect = requests.Timeout()
        with patch.object(main, 'create_cookie_session', return_value=session), patch.object(main, 'notify'):
            self.assertFalse(main.sign_with_cookie(1, 'https://example.com', 'sid=test'))

    def test_no_push_when_key_missing(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(main.requests, 'post') as post:
            main.notify('测试')
            post.assert_not_called()

    def test_notification_failure_does_not_raise(self):
        with patch.dict(os.environ, {'SCKEY': 'test'}), patch.object(main.requests, 'post', side_effect=requests.Timeout()):
            main.notify('测试')


if __name__ == '__main__':
    unittest.main()
