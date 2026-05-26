#!/usr/bin/env python3
"""
KBO 경기 일정/결과 수집기
Usage: python kbo_fetch.py
Output: kbo_data.json  (오늘 + 최근 3일)
"""

import json
import re
from datetime import datetime, timedelta
import urllib.request
import urllib.error

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124',
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9',
}

TEAM_MAP = {
    'LG': 'LG 트윈스',      'LG트윈스': 'LG 트윈스',
    'OB': '두산 베어스',     '두산': '두산 베어스',
    '키움': '키움 히어로즈', '히어로즈': '키움 히어로즈',
    'SSG': 'SSG 랜더스',    '랜더스': 'SSG 랜더스',
    'KT':  'kt wiz',        'kt': 'kt wiz',
    '한화': '한화 이글스',
    '삼성': '삼성 라이온즈',
    'KIA': 'KIA 타이거즈',   '기아': 'KIA 타이거즈',
    'NC':  'NC 다이노스',
    '롯데': '롯데 자이언츠',
}

STATUS_MAP = {
    'CANCEL': '취소', 'POSTPONE': '우천취소',
    'GAME_OVER': '종료', 'LIVE': '진행 중',
    'READY': '예정', 'BEFORE': '예정', 'PREPARED': '예정',
}


def get(url, extra_headers=None):
    h = {**HEADERS, **(extra_headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=15) as r:
        charset = r.headers.get_content_charset() or 'utf-8'
        return r.read().decode(charset)


def normalize(name):
    if not name:
        return name
    return TEAM_MAP.get(name.strip(), name.strip())


# ── Naver Sports (여러 엔드포인트 시도) ──────────────────────────────────────

def try_naver(date_str):
    candidates = [
        f'https://sports.news.naver.com/kbaseball/schedule/gameList.nhn?date={date_str}',
        f'https://api-gw.sports.naver.com/schedule/games?sports=kbo&date={date_str}',
    ]
    for url in candidates:
        try:
            raw = get(url, {'Referer': 'https://sports.news.naver.com/'})
            data = json.loads(raw)
            game_list = (
                data.get('result', {}).get('games') or
                data.get('games') or
                data.get('list') or []
            )
            if not game_list:
                continue
            games = []
            for g in game_list:
                sc = g.get('statusCode', 'READY')
                a_s = g.get('awayScore')
                h_s = g.get('homeScore')
                games.append({
                    'time':       g.get('gameTime', ''),
                    'away':       normalize(g.get('awayTeamName', '')),
                    'home':       normalize(g.get('homeTeamName', '')),
                    'away_score': None if a_s in ('', None) else str(a_s),
                    'home_score': None if h_s in ('', None) else str(h_s),
                    'status':     STATUS_MAP.get(sc, sc),
                    'stadium':    g.get('stadiumName', ''),
                })
            print(f'[Naver] {date_str}: {len(games)}경기')
            return games
        except Exception as e:
            print(f'[Naver] {url}: {e}')
    return None


# ── KBO 공식 홈페이지 파싱 ────────────────────────────────────────────────────

def try_kbo_html(date_str):
    year = date_str[:4]
    url = (f'https://www.kbo.or.kr/schedule/schedule_list.asp'
           f'?leId=1&srId=0&seasonId={year}&date={date_str}')
    try:
        html = get(url, {'Referer': 'https://www.kbo.or.kr/'})
    except Exception as e:
        print(f'[KBO HTML] {date_str}: {e}')
        return None

    try:
        from bs4 import BeautifulSoup
    except ImportError:
        print('[KBO HTML] pip install beautifulsoup4 필요')
        return None

    try:
        soup = BeautifulSoup(html, 'html.parser')
        games = []

        table = (
            soup.find('table', class_=re.compile(r'sch', re.I)) or
            soup.find('table')
        )
        if not table:
            print(f'[KBO HTML] {date_str}: 테이블 없음')
            return None

        for tr in table.find_all('tr'):
            tds = [td.get_text(separator=' ', strip=True) for td in tr.find_all('td')]
            if len(tds) < 4:
                continue
            # 시간 컬럼 찾기 (HH:MM 형식)
            time_val = next((t for t in tds if re.match(r'^\d{1,2}:\d{2}$', t)), None)
            if not time_val:
                continue
            ti = tds.index(time_val)

            score_raw = tds[ti + 2] if ti + 2 < len(tds) else ''
            m = re.search(r'(\d+)\s*[:\-]\s*(\d+)', score_raw)
            a_s = m.group(1) if m else None
            h_s = m.group(2) if m else None

            games.append({
                'time':       time_val,
                'away':       normalize(tds[ti + 1]) if ti + 1 < len(tds) else '',
                'home':       normalize(tds[ti + 3]) if ti + 3 < len(tds) else '',
                'away_score': a_s,
                'home_score': h_s,
                'status':     '종료' if a_s else '예정',
                'stadium':    tds[ti + 4] if ti + 4 < len(tds) else '',
            })

        print(f'[KBO HTML] {date_str}: {len(games)}경기')
        return games or None
    except Exception as e:
        print(f'[KBO HTML] {date_str}: 파싱 오류 {e}')
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_day(date_str):
    return try_naver(date_str) or try_kbo_html(date_str) or []


def main():
    today = datetime.now()
    # 오늘 + 과거 3일 수집
    date_strs = [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(4)]

    # 기존 데이터 로드
    try:
        with open('kbo_data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
    except Exception:
        existing = {}

    dates_data = existing.get('dates', {})

    for ds in date_strs:
        df = f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'
        games = fetch_day(ds)
        dates_data[df] = {'date': df, 'games': games}

    # 최근 7일만 보관
    keep = sorted(dates_data.keys(), reverse=True)[:7]
    dates_data = {k: dates_data[k] for k in keep}

    result = {
        'updated': today.strftime('%Y-%m-%dT%H:%M:%S'),
        'today':   today.strftime('%Y-%m-%d'),
        'dates':   dates_data,
    }

    with open('kbo_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(v['games']) for v in dates_data.values())
    print(f'저장 완료: kbo_data.json ({len(dates_data)}일, {total}경기)')


if __name__ == '__main__':
    main()
