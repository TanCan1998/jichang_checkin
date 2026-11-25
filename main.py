import os
import re
import sys
from urllib.parse import urlsplit

import requests

TIMEOUT = 30
TRAFFIC_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3, 'TB': 1024 ** 4}


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


def parse_traffic(value):
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return None
    match = re.search(r'([\d,.]+)\s*(B|KB|MB|GB|TB)?', value, re.IGNORECASE)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(',', ''))
    except ValueError:
        return None
    unit = (match.group(2) or 'B').upper()
    return int(amount * TRAFFIC_UNITS[unit])


def find_value(data, names, convert):
    names = {name.lower().replace('_', '') for name in names}
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower().replace('_', '') in names:
                parsed = convert(value)
                if parsed is not None:
                    return parsed
        for value in data.values():
            parsed = find_value(value, names, convert)
            if parsed is not None:
                return parsed
    elif isinstance(data, list):
        for value in data:
            parsed = find_value(value, names, convert)
            if parsed is not None:
                return parsed
    return None


def extract_checkin_stats(result, message):
    traffic_info = find_value(result, ('trafficInfo',), lambda value: value)
    reward = find_value(result, (
        'checkin_traffic', 'checkinTraffic', 'traffic_reward', 'trafficReward',
        'reward_traffic', 'rewardTraffic', 'trafficInfo',
    ), parse_traffic)
    if reward is None and traffic_info is not None:
        reward = find_value(
            traffic_info, ('reward', 'traffic', 'amount', 'value'), parse_traffic,
        )
    if reward is None:
        match = re.search(
            r'(?:获得|奖励|增加)\s*([\d,.]+\s*(?:B|KB|MB|GB|TB)?)',
            message, re.IGNORECASE,
        )
        if match:
            reward = parse_traffic(match.group(1))

    def parse_days(value):
        if isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    checkin_days = find_value(result, (
        'checkin_days', 'checkinDays', 'total_checkin_days', 'totalCheckinDays',
        'checkin_count', 'checkinCount',
    ), parse_days)
    quota = find_value(result, (
        'transfer_enable', 'transferEnable', 'total_traffic', 'totalTraffic',
    ), parse_traffic)
    remaining = find_value(result, (
        'remaining_traffic', 'remainingTraffic', 'traffic_left', 'trafficLeft',
    ), parse_traffic)
    if remaining is None and quota is not None:
        uploaded = find_value(result, ('u', 'upload', 'uploaded'), parse_traffic)
        downloaded = find_value(result, ('d', 'download', 'downloaded'), parse_traffic)
        if uploaded is not None and downloaded is not None:
            remaining = max(0, quota - uploaded - downloaded)
    return {
        'checkin_days': checkin_days,
        'reward': reward,
        'remaining': remaining,
        'quota': quota,
    }


def format_traffic(value):
    if value is None:
        return '未返回'
    amount = float(value)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if amount < 1024 or unit == 'TB':
            return f'{amount:.2f}'.rstrip('0').rstrip('.') + f' {unit}'
        amount /= 1024


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
    return success, content, extract_checkin_stats(result, message)


def create_cookie_session():
    from curl_cffi import requests as browser_requests
    return browser_requests.Session(impersonate='chrome')


def sign_with_cookie(order, url, cookie):
    try:
        with create_cookie_session() as session:
            session.headers.update({'Cookie': cookie, 'origin': url, 'referer': f'{url}/user'})
            success, content, stats = check_in(session, url)
    except Exception as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        detail = f'HTTP {status}' if status else type(exc).__name__
        success, content = False, f'Cookie 签到失败：{detail}，请检查会话是否过期或网络是否正常'
        stats = extract_checkin_stats({}, '')
    detail = (
        f'累计签到 {stats["checkin_days"] if stats["checkin_days"] is not None else "未返回"} 天，'
        f'本次获得 {format_traffic(stats["reward"])}，'
        f'当前剩余 {format_traffic(stats["remaining"])}'
        + (f' / {format_traffic(stats["quota"])}' if stats['quota'] is not None else '')
    )
    print(f'账号 {order}：{content}；{detail}')
    notify(f'账号 {order}：{content}；{detail}')
    return success, stats


def report_summary(results):
    successes = sum(success for success, _ in results)
    lines = [
        f'已签到账号：{successes}/{len(results)}（成功或今日已签到）',
        '运行摘要：',
        '| 账号 | 签到状态 | 累计签到天数 | 本次签到流量 | 当前剩余流量 |',
        '| --- | --- | ---: | ---: | ---: |',
    ]
    for order, (success, stats) in enumerate(results, start=1):
        status = '已签到' if success else '失败'
        days = stats['checkin_days']
        remaining = format_traffic(stats['remaining'])
        if stats['quota'] is not None:
            remaining += f' / {format_traffic(stats["quota"])}'
        lines.append(
            f'| 账号 {order} | {status} | '
            f'{days if days is not None else "未返回"} 天 | '
            f'{format_traffic(stats["reward"])} | {remaining} |'
        )
    report = '\n'.join(lines)
    print(report)
    summary_path = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary_path:
        with open(summary_path, 'a', encoding='utf-8') as summary_file:
            summary_file.write(report + '\n')
    return successes


def main():
    try:
        url, cookies = load_config()
    except ValueError as exc:
        print(f'配置错误：{exc}')
        return 1
    results = [
        sign_with_cookie(i, url, cookie)
        for i, cookie in enumerate(cookies, start=1)
    ]
    successes = report_summary(results)
    return 0 if successes == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
