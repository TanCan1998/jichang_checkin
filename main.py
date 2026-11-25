import os
import sys
from urllib.parse import urlsplit

import requests

TIMEOUT = 30


def load_config():
    url = os.environ.get('URL', '').strip().rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('请在 Secrets.URL 中填写有效的网站地址')
    cookies = os.environ.get('COOKIE', '').strip()
    lines = cookies.splitlines()
    if not lines or any(not line.strip() or '=' not in line for line in lines):
        raise ValueError('请在 Secrets.COOKIE 中填写请求头 Cookie，每个账号一行')
    return url, [line.strip() for line in lines]


def already_checked_in(message):
    return any(text in message for text in ('已经签到', '已签到', '已经签过', '已签过'))


def response_ok(result):
    return str(result.get('ret', '')).lower() in ('1', 'true')


def notify(content):
    key = os.environ.get('SCKEY', '').strip()
    if not key:
        return
    try:
        response = requests.post(
            f'https://sctapi.ftqq.com/{key}.send',
            data={'title': '机场签到', 'desp': content}, timeout=TIMEOUT,
        )
        response.raise_for_status()
        if response.json().get('code') != 0:
            raise ValueError('推送服务返回失败')
        print('推送成功')
    except Exception as exc:
        print(f'推送失败：{type(exc).__name__}')


def check_in(session, url):
    response = session.post(f'{url}/user/checkin', timeout=TIMEOUT)
    response.raise_for_status()
    result = response.json()
    message = str(result.get('msg', ''))
    success = response_ok(result) or already_checked_in(message)
    content = '今日已签到' if already_checked_in(message) else ('签到成功' if success else '签到接口返回失败，请检查 Cookie 或站点状态')
    return success, content


def create_cookie_session():
    from curl_cffi import requests as browser_requests
    return browser_requests.Session(impersonate='chrome')


def sign_with_cookie(order, url, cookie):
    try:
        with create_cookie_session() as session:
            session.headers.update({'Cookie': cookie, 'origin': url, 'referer': f'{url}/user'})
            success, content = check_in(session, url)
    except Exception as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        detail = f'HTTP {status}' if status else type(exc).__name__
        success, content = False, f'Cookie 签到失败：{detail}，请检查会话是否过期或网络是否正常'
    print(f'账号 {order}：{content}')
    notify(f'账号 {order}：{content}')
    return success


def main():
    try:
        url, cookies = load_config()
    except ValueError as exc:
        print(f'配置错误：{exc}')
        return 1
    results = [sign_with_cookie(i, url, cookie)
               for i, cookie in enumerate(cookies, start=1)]
    print(f'签到完成：{sum(results)}/{len(results)} 个账号成功或今日已签到')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
