import os
import tempfile
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
                patch.object(main, 'sign_with_cookie', side_effect=[
                    (False, main.extract_checkin_stats({}, '')),
                    (True, main.extract_checkin_stats({}, '')),
                ]) as sign, patch.object(main, 'report_summary', return_value=1):
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
                    self.assertEqual(main.sign_with_cookie(1, 'https://example.com', 'sid=test')[0], expected)
                    self.assertEqual(session.headers.update.call_args.args[0]['Cookie'], 'sid=test')
                    self.assertEqual(session.post.call_args.args[0], 'https://example.com/user/checkin')

    def test_already_checked_in_is_identified_in_run_summary(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value.json.return_value = {
            'ret': 0,
            'msg': '您今天已经签到过了',
        }
        with patch.object(main, 'create_cookie_session', return_value=session), \
                patch.object(main, 'notify'):
            success, stats = main.sign_with_cookie(1, 'https://example.com', 'sid=test')
        self.assertTrue(success)
        self.assertEqual(stats['status'], '今日已签到')

    def test_checkin_summary_extracts_reward_days_and_remaining_traffic(self):
        result = {
            'ret': 1,
            'msg': '签到成功，获得了 1 GB 流量',
            'data': {
                'checkin_days': 12,
                'transfer_enable': 10 * 1024 ** 3,
                'u': 2 * 1024 ** 3,
                'd': 3 * 1024 ** 3,
            },
        }
        stats = main.extract_checkin_stats(result, result['msg'])
        self.assertEqual(stats, {
            'checkin_days': 12,
            'reward': 1024 ** 3,
            'remaining': 5 * 1024 ** 3,
            'quota': 10 * 1024 ** 3,
        })

    def test_account_page_does_not_infer_exact_quota_from_rounded_usage(self):
        html = '''
            <span>过去用量 1 GB</span>
            <span>今日用量 512 MB</span>
            <span>剩余流量 2.5 GB</span>
        '''
        self.assertEqual(main.parse_account_page(html), {
            'remaining': int(2.5 * 1024 ** 3),
            'quota': None,
            'subscription_url': None,
        })

    def test_subscription_json_provides_exact_quota_and_remaining(self):
        response = MagicMock()
        response.text = '''
            <input id="universal-sub-link" value="https://example.com/sub/token">
            <span>过去用量 1 GB</span>
            <span>今日用量 512 MB</span>
            <span>剩余流量 2.5 GB</span>
        '''
        subscription_response = MagicMock()
        subscription_response.json.return_value = {
            'total_traffic': 10 * 1024 ** 3,
            'used_upload_traffic': 2 * 1024 ** 3,
            'used_download_traffic': 3 * 1024 ** 3,
        }
        session = MagicMock()
        session.get.side_effect = [response, subscription_response]

        self.assertEqual(main.fetch_account_traffic(session, 'https://example.com'), {
            'remaining': 5 * 1024 ** 3,
            'quota': 10 * 1024 ** 3,
        })
        self.assertEqual(
            session.get.call_args_list[1].args[0],
            'https://example.com/sub/token/json',
        )

    def test_subscription_link_to_other_origin_is_never_requested(self):
        response = MagicMock()
        response.text = '<input id="universal-sub-link" value="https://other.example/sub/token">'
        session = MagicMock()
        session.get.return_value = response

        self.assertEqual(main.fetch_account_traffic(session, 'https://example.com'), {
            'remaining': None,
            'quota': None,
        })
        session.get.assert_called_once_with('https://example.com/user', timeout=main.TIMEOUT)

    def test_checkin_message_parses_standard_sspanel_reward(self):
        stats = main.extract_checkin_stats(
            {'ret': 1, 'msg': '获得了 128MB 流量'},
            '获得了 128MB 流量',
        )
        self.assertEqual(stats['reward'], 128 * 1024 ** 2)

    def test_sign_with_cookie_combines_checkin_and_profile_data(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.return_value.json.return_value = {
            'ret': 1,
            'msg': '获得了 128MB 流量',
        }
        profile_response = MagicMock()
        profile_response.text = '<input id="universal-sub-link" value="https://example.com/sub/token">'
        subscription_response = MagicMock()
        subscription_response.json.return_value = {
            'total_traffic': 10 * 1024 ** 3,
            'used_upload_traffic': 2 * 1024 ** 3,
            'used_download_traffic': 3 * 1024 ** 3,
        }
        session.get.side_effect = [profile_response, subscription_response]
        with patch.object(main, 'create_cookie_session', return_value=session), \
                patch.object(main, 'notify'):
            success, stats = main.sign_with_cookie(1, 'https://example.com', 'sid=test')
        self.assertTrue(success)
        self.assertEqual(stats['reward'], 128 * 1024 ** 2)
        self.assertEqual(stats['remaining'], 5 * 1024 ** 3)
        self.assertEqual(stats['quota'], 10 * 1024 ** 3)
        self.assertEqual(
            session.get.call_args_list[0].args[0],
            'https://example.com/user',
        )
        self.assertEqual(
            session.get.call_args_list[1].args[0],
            'https://example.com/sub/token/json',
        )

    def test_run_summary_is_written_to_github_step_summary(self):
        stats = {
            'checkin_days': 12,
            'reward': 1024 ** 2,
            'remaining': 2 * 1024 ** 3,
            'quota': 10 * 1024 ** 3,
            'status': '今日已签到',
        }
        with tempfile.NamedTemporaryFile(mode='r+', encoding='utf-8') as summary_file, \
                patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': summary_file.name}):
            self.assertEqual(main.report_summary([(True, stats)]), 1)
            summary_file.seek(0)
            content = summary_file.read()
        self.assertIn('1/1', content)
        self.assertIn('12 天', content)
        self.assertIn('今日已签到', content)
        self.assertIn('1 MB', content)
        self.assertIn('2 GB / 10 GB', content)

    def test_cookie_request_timeout_fails(self):
        session = MagicMock()
        session.__enter__.return_value = session
        session.post.side_effect = requests.Timeout()
        with patch.object(main, 'create_cookie_session', return_value=session), patch.object(main, 'notify'):
            self.assertFalse(main.sign_with_cookie(1, 'https://example.com', 'sid=test')[0])

    def test_no_push_when_key_missing(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(main.requests, 'post') as post:
            main.notify('测试')
            post.assert_not_called()

    def test_notification_failure_does_not_raise(self):
        with patch.dict(os.environ, {'SCKEY': 'test'}), patch.object(main.requests, 'post', side_effect=requests.Timeout()):
            main.notify('测试')


if __name__ == '__main__':
    unittest.main()
