#!/usr/bin/env python3
"""
KBO 경기 일정/결과 수집기  (Playwright headless 우선)
Usage: python kbo_fetch.py
Output: kbo_data.json
"""

import json
import re
from datetime import datetime, timedelta
import urllib.request

BASE_HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/124.0.0.0 Safari/537.36'
    ),
    'Accept': 'application/json, text/html, */*',
    'Accept-Language': 'ko-KR,ko;q=0.9,en;q=0.8',
}

TEAM_MAP = {
    'LG': 'LG 트윈스',      'LG트윈스': 'LG 트윈스',
    'OB': '두산 베어스',     'DB': '두산 베어스',     '두산': '두산 베어스',
    '키움': '키움 히어로즈', '히어로즈': '키움 히어로즈', 'WO': '키움 히어로즈',
    'SSG': 'SSG 랜더스',    '랜더스': 'SSG 랜더스',  'SK': 'SSG 랜더스',
    'KT':  'kt wiz',        'kt': 'kt wiz',
    '한화': '한화 이글스',   'HH': '한화 이글스',
    '삼성': '삼성 라이온즈', 'SS': '삼성 라이온즈',
    'KIA': 'KIA 타이거즈',  '기아': 'KIA 타이거즈',  'HT': 'KIA 타이거즈',
    'NC':  'NC 다이노스',
    '롯데': '롯데 자이언츠', 'LT': '롯데 자이언츠',
}

STATUS_MAP = {
    'CANCEL':    '취소',
    'POSTPONE':  '우천취소',
    'GAME_OVER': '종료',
    'LIVE':      '진행 중',
    'READY':     '예정',
    'BEFORE':    '예정',
    'PREPARED':  '예정',
}

STADIUM_MAP = {
    '잠실': '잠실야구장', '고척': '고척스카이돔',
    '문학': 'SSG 랜더스필드', '인천': 'SSG 랜더스필드',
    '수원': 'kt wiz 파크',
    '대전': '한화생명 이글스파크',
    '대구': '삼성 라이온즈파크',
    '광주': '광주-기아 챔피언스필드',
    '창원': '창원 NC 파크',
    '사직': '사직야구장', '부산': '사직야구장',
}


def normalize_team(name):
    if not name:
        return name
    name = name.strip()
    return TEAM_MAP.get(name, name)


def normalize_stadium(name):
    if not name:
        return name
    name = name.strip()
    if name in STADIUM_MAP:
        return STADIUM_MAP[name]
    for k, v in STADIUM_MAP.items():
        if k in name:
            return v
    return name


def http_get(url, extra_headers=None):
    h = {**BASE_HEADERS, **(extra_headers or {})}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode(r.headers.get_content_charset() or 'utf-8')


# ── 1) Playwright: koreabaseball.com (headless Chrome) ───────────────────────
def try_playwright(date_str):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[Playwright] 미설치 — pip install playwright && playwright install chromium')
        return None

    year  = date_str[:4]
    month = date_str[4:6].lstrip('0')
    day   = date_str[6:].lstrip('0')

    captured = []   # 네트워크 응답에서 잡힌 JSON 게임 데이터

    def on_response(response):
        """XHR/fetch 응답 인터셉트: JSON 게임 데이터 캡처"""
        url = response.url
        if not any(k in url for k in ('Schedule', 'Game', 'schedule', 'game')):
            return
        try:
            ct = response.headers.get('content-type', '')
            if 'json' not in ct and 'javascript' not in ct:
                return
            data = response.json()
            # 다양한 응답 키 시도
            game_list = (
                data.get('data') or
                data.get('games') or
                data.get('result', {}).get('games') or
                data.get('list') or []
            )
            if game_list:
                captured.extend(game_list)
                print(f'[Playwright XHR] {len(game_list)}경기 캡처: {url}')
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx  = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
            )
            page = ctx.new_page()
            page.on('response', on_response)

            # 날짜 파라미터 포함 URL
            url = (
                f'https://www.koreabaseball.com/Schedule/Schedule.aspx'
                f'?seriesId=0&teamId=0&gameDate={date_str}'
            )
            print(f'[Playwright] {url} 로딩 중...')
            page.goto(url, wait_until='networkidle', timeout=30000)

            # 테이블 행이 생길 때까지 최대 5초 추가 대기
            try:
                page.wait_for_selector('table tbody tr td', timeout=5000)
            except Exception:
                pass

            # 디버그: 테이블 첫 500자 출력
            try:
                tbl_html = page.eval_on_selector('table', 'el => el.outerHTML')
                print(f'[Playwright DEBUG table] {tbl_html[:500]}')
            except Exception as e:
                print(f'[Playwright DEBUG] 테이블 없음: {e}')
                # 페이지 전체 텍스트 일부 출력
                txt = page.inner_text('body')
                print(f'[Playwright DEBUG body] {txt[:300]}')

            # XHR로 못 잡았으면 HTML 테이블 파싱
            if not captured:
                games = _parse_kbo_html_table(page, date_str)
                browser.close()
                return games if games else None

            browser.close()

        # XHR 캡처 데이터 파싱
        games = []
        for g in captured:
            sc  = g.get('statusCode', g.get('gameStatus', 'READY'))
            a_s = g.get('awayScore', g.get('visitScore'))
            h_s = g.get('homeScore')
            games.append({
                'time':       g.get('gameTime', g.get('time', '')),
                'away':       normalize_team(g.get('awayTeamCode') or g.get('awayTeamName') or g.get('visitTeamCode', '')),
                'home':       normalize_team(g.get('homeTeamCode') or g.get('homeTeamName', '')),
                'away_score': None if a_s in ('', None) else str(a_s),
                'home_score': None if h_s in ('', None) else str(h_s),
                'status':     STATUS_MAP.get(sc, sc),
                'stadium':    normalize_stadium(g.get('stadiumName', g.get('stadium', ''))),
            })
        print(f'[Playwright] {date_str}: {len(games)}경기')
        return games or None

    except Exception as e:
        print(f'[Playwright] 오류: {e}')
        return None


def _parse_kbo_html_table(page, date_str):
    """Playwright page 객체에서 schedule 테이블 HTML 파싱"""
    try:
        from bs4 import BeautifulSoup
        html = page.content()
        soup = BeautifulSoup(html, 'html.parser')
        return _extract_games_from_soup(soup, date_str)
    except Exception as e:
        print(f'[Playwright HTML parse] {e}')
        return None


def _extract_games_from_soup(soup, date_str):
    """
    koreabaseball.com tblScheduleList 실제 구조:
    <td class="day" rowspan="N">날짜</td>
    <td class="time"><b>HH:MM</b></td>
    <td class="play">
      <span>원정팀</span>
      <em><span class="win/lose">6</span><span>vs</span><span class="win/lose">0</span></em>
      <span>홈팀</span>
    </td>
    ... (relay, highlight, TV, radio)
    <td>구장</td>
    <td>비고</td>
    """
    y, mo, d  = date_str[:4], date_str[4:6], date_str[6:]
    date_pats = [
        f'{y}.{mo}.{d}',
        f'{y}-{mo}-{d}',
        f'{int(mo)}.{int(d)}',
        f'{mo}.{d}',
    ]

    table = (
        soup.find('table', id='tblScheduleList') or
        soup.find('table', class_='tbl') or
        soup.find('table')
    )
    if not table:
        print(f'[KBO HTML Table] {date_str}: 테이블 없음')
        return None

    rows = table.find_all('tr')
    print(f'[KBO HTML Table] {date_str}: {len(rows)}행')

    games           = []
    current_matched = False

    for tr in rows:
        # ── 날짜 셀 감지 (td.day, rowspan) ──
        day_td = tr.find('td', class_='day')
        if day_td:
            day_text = day_td.get_text(strip=True)
            current_matched = any(pat in day_text for pat in date_pats)

        if not current_matched:
            continue

        # ── 시간 셀 ──
        time_td = tr.find('td', class_='time')
        if not time_td:
            continue
        time_val = time_td.get_text(strip=True)
        if not re.match(r'^\d{1,2}:\d{2}$', time_val):
            continue

        # ── 경기 셀 (td.play) ──
        play_td = tr.find('td', class_='play')
        if not play_td:
            continue

        # 원정/홈팀: play 직계 자식 <span>
        team_spans = play_td.find_all('span', recursive=False)
        away = normalize_team(team_spans[0].get_text(strip=True)) if team_spans else ''
        home = normalize_team(team_spans[-1].get_text(strip=True)) if len(team_spans) > 1 else ''

        # 스코어: <em> 내부 숫자 <span>
        a_s = h_s = None
        status = '예정'
        em = play_td.find('em')
        if em:
            score_spans = [s for s in em.find_all('span')
                           if s.get_text(strip=True).isdigit()]
            if len(score_spans) >= 2:
                a_s    = score_spans[0].get_text(strip=True)
                h_s    = score_spans[1].get_text(strip=True)
                status = '종료'

        # 취소 여부: 비고(마지막 td) 또는 play 텍스트
        all_tds = tr.find_all('td')
        note    = all_tds[-1].get_text(strip=True) if all_tds else ''
        if any(k in note for k in ('취소', '우천')) or \
           any(k in play_td.get_text() for k in ('취소', '우천')):
            status = '우천취소'
            a_s = h_s = None

        # 구장: 뒤에서 두 번째 td
        stad_raw = all_tds[-2].get_text(strip=True) if len(all_tds) >= 2 else ''

        if not away or not home:
            continue

        games.append({
            'time':       time_val,
            'away':       away,
            'home':       home,
            'away_score': a_s,
            'home_score': h_s,
            'status':     status,
            'stadium':    normalize_stadium(stad_raw),
        })

    print(f'[KBO HTML Table] {date_str}: {len(games)}경기')
    return games or None


# ── 2) Naver Sports API (urllib 폴백) ─────────────────────────────────────────
def try_naver(date_str):
    candidates = [
        (
            f'https://api-gw.sports.naver.com/schedule/games'
            f'?category=kbo&date={date_str}&roundCode=&pageSize=20&pageNo=1',
            {'Referer': 'https://sports.naver.com/', 'Origin': 'https://sports.naver.com'},
        ),
        (
            f'https://api-gw.sports.naver.com/schedule/games'
            f'?leagueCode=kbo&date={date_str}&pageSize=20&pageNo=1',
            {'Referer': 'https://sports.naver.com/', 'Origin': 'https://sports.naver.com'},
        ),
    ]
    for url, extra in candidates:
        try:
            data = json.loads(http_get(url, extra))
            game_list = (
                data.get('result', {}).get('games') or
                data.get('games') or
                data.get('list') or []
            )
            if not game_list:
                continue
            games = []
            for g in game_list:
                sc  = g.get('statusCode', 'READY')
                a_s = g.get('awayScore')
                h_s = g.get('homeScore')
                games.append({
                    'time':       g.get('gameTime', ''),
                    'away':       normalize_team(g.get('awayTeamCode') or g.get('awayTeamName', '')),
                    'home':       normalize_team(g.get('homeTeamCode') or g.get('homeTeamName', '')),
                    'away_score': None if a_s in ('', None) else str(a_s),
                    'home_score': None if h_s in ('', None) else str(h_s),
                    'status':     STATUS_MAP.get(sc, sc),
                    'stadium':    normalize_stadium(g.get('stadiumName', '')),
                })
            print(f'[Naver] {date_str}: {len(games)}경기')
            return games
        except Exception as e:
            print(f'[Naver] {date_str}: {e}')
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_day(date_str):
    return (
        try_playwright(date_str) or
        try_naver(date_str) or
        []
    )


def main():
    today     = datetime.now()
    date_strs = [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(4)]

    try:
        with open('kbo_data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
    except Exception:
        existing = {}

    dates_data = existing.get('dates', {})

    for ds in date_strs:
        df    = f'{ds[:4]}-{ds[4:6]}-{ds[6:]}'
        games = fetch_day(ds)
        dates_data[df] = {'date': df, 'games': games}

    keep       = sorted(dates_data.keys(), reverse=True)[:7]
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
