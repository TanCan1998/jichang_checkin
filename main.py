import os
import base64
import re
import sys
import time
from urllib.parse import urlsplit, urljoin
from html.parser import HTMLParser

import requests

CAPTCHA_ID = 'cc96d05ba8b60f9112f76e18526fcb73'
MAX_RETRIES = 3
TIMEOUT = 30


def decode_login_html(html):
    for _ in range(3):
        match = re.search(r'''\boriginBody\s*=\s*['"]([A-Za-z0-9+/=]+)['"]''', html)
        if not match:
            break
        html = base64.b64decode(match.group(1)).decode('utf-8')
    return html


class LoginPage(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = {}
        self.csrf = None
        self.scripts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.scripts.append(attrs['src'])
        if tag == 'input' and attrs.get('type', '').lower() == 'hidden' and attrs.get('name'):
            self.fields[attrs['name']] = attrs.get('value', '')
        if tag == 'meta' and attrs.get('name') == 'csrf-token':
            self.csrf = attrs.get('content')


def load_config():
    url = os.environ.get('URL', '').strip().rstrip('/')
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('请在 Secrets.URL 中填写有效的网站地址')
    lines = os.environ.get('CONFIG', '').strip().splitlines()
    if not lines or len(lines) % 2 or any(not line.strip() for line in lines):
        raise ValueError('Secrets.CONFIG 必须按一行账号、一行密码成对填写，不能有空行')
    return url, list(zip(lines[::2], lines[1::2]))


def solve_captcha(captcha_id=CAPTCHA_ID):
    from geeked import Geeked

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            print(f'验证码求解尝试 {attempt}/{MAX_RETRIES}')
            result = Geeked(captcha_id, 'ai', timeout=TIMEOUT).solve()
            if not all(result.get(key) for key in ('lot_number', 'captcha_output', 'pass_token', 'gen_time')):
                raise ValueError('验证码返回字段不完整')
            return result
        except Exception as exc:
            # 上游异常可能包含验证码令牌，不输出异常正文。
            print(f'验证码求解失败：{type(exc).__name__}')
            if attempt < MAX_RETRIES:
                time.sleep(2)
    raise RuntimeError('验证码求解重试全部失败')


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


def sign(order, url, user, password):
    print(f'===账号 {order} 开始签到===')
    success = False
    try:
        data = {'email': user.strip(), 'passwd': password}
        with requests.Session() as session:
            session.headers.update({'origin': url, 'referer': f'{url}/auth/login', 'user-agent': 'Mozilla/5.0 Chrome/124.0.0.0 Safari/537.36'})
            page = session.get(f'{url}/auth/login', timeout=TIMEOUT)
            page.raise_for_status()
            html = decode_login_html(page.text)
            form = LoginPage(html)
            data = form.fields | data
            if form.csrf:
                session.headers['X-CSRF-TOKEN'] = form.csrf
            if 'buildLoginRequest' in html:
                data.update({'host': urlsplit(url).netloc, 'phase': 'password',
                             'pageLoadedAt': int(time.time() * 1000), 'remember_me': 'week'})
            login = session.post(f'{url}/auth/login', data=data, timeout=TIMEOUT)
            login.raise_for_status()
            login_result = login.json()
            if not response_ok(login_result):
                message = str(login_result.get('msg', '')).lower()
                if any(word in message for word in ('验证码', 'captcha', 'geetest', '验证失败', '验证结果', '人机')):
                    match = re.search(r'''(?:captchaId|captcha_id)\s*['"]?\s*[:=]\s*['"]([a-f0-9]{32})['"]''', html)
                    captcha_id = match.group(1) if match else CAPTCHA_ID
                    captcha = solve_captcha(captcha_id)
                    data.update({f'captcha_result[{key}]': captcha[key]
                                 for key in ('lot_number', 'captcha_output', 'pass_token', 'gen_time')})
                    login = session.post(f'{url}/auth/login', data=data, timeout=TIMEOUT)
                    login.raise_for_status()
                    login_result = login.json()
            if not response_ok(login_result):
                message = str(login_result.get('msg', '无错误说明'))
                for value in (user, password, url):
                    if value:
                        message = message.replace(value, '[隐藏]')
                print('登录接口提示：' + message.replace('\n', ' ').replace('\r', ' ')[:200])
                raise RuntimeError('登录失败，请检查账号密码或验证码')
            response = session.post(f'{url}/user/checkin', timeout=TIMEOUT)
            response.raise_for_status()
            result = response.json()
            message = str(result.get('msg', ''))
            success = response_ok(result) or already_checked_in(message)
            # 不打印服务端原始内容，防止公开日志包含账号、令牌等信息。
            content = '今日已签到' if already_checked_in(message) else ('签到成功' if success else '签到接口返回失败')
    except Exception as exc:
        content = f'签到失败：{type(exc).__name__}'
    print(f'账号 {order}：{content}')
    notify(f'账号 {order}：{content}')
    return success


def main():
    try:
        url, accounts = load_config()
    except ValueError as exc:
        print(f'配置错误：{exc}')
        return 1
    results = [sign(i, url, user, password)
               for i, (user, password) in enumerate(accounts, start=1)]
    print(f'签到完成：{sum(results)}/{len(results)} 个账号成功或今日已签到')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
