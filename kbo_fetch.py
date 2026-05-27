#!/usr/bin/env python3
"""
KBO 경기 일정/결과 수집기  (달력 뷰 우선)
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

# 알려진 팀명 전체 목록 (달력 텍스트 파싱용)
ALL_TEAM_NAMES = set(TEAM_MAP.keys()) | set(TEAM_MAP.values())


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


# ── 1) 달력 뷰 파싱 (Primary) ────────────────────────────────────────────────
def try_kbo_calendar(date_str):
    """
    koreabaseball.com 달력 탭에서 특정 날짜 경기 파싱
    - 경기시간은 달력에 표시되지 않아 빈 값으로 처리
    """
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print('[Calendar] playwright/bs4 미설치')
        return None

    year  = date_str[:4]
    month = date_str[4:6]
    day   = int(date_str[6:])

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
            )
            page = ctx.new_page()

            # 리스트 뷰 URL로 이동 후 달력 탭 클릭
            url = (
                f'https://www.koreabaseball.com/Schedule/Schedule.aspx'
                f'?seriesId=0&teamId=0&gameDate={date_str}'
            )
            print(f'[Calendar] {url} 로딩 중...')
            page.goto(url, wait_until='networkidle', timeout=30000)

            # 달력 탭 클릭
            try:
                page.click('text=달력', timeout=5000)
                page.wait_for_load_state('networkidle', timeout=15000)
                print('[Calendar] 달력 탭 클릭 완료')
            except Exception as e:
                print(f'[Calendar] 달력 탭 클릭 실패: {e}')

            # 년/월 select 값 확인 및 조정
            try:
                cur_year  = page.eval_on_selector(
                    'select[name*="year"], select[id*="year"], select[id*="Year"]',
                    'el => el.value'
                )
                cur_month = page.eval_on_selector(
                    'select[name*="month"], select[id*="month"], select[id*="Month"]',
                    'el => el.value'
                )
                if str(cur_year) != year or str(int(cur_month)) != str(int(month)):
                    print(f'[Calendar] 현재 {cur_year}/{cur_month} → {year}/{int(month)} 로 변경 필요')
                    # select 값 변경 후 이벤트 발생
                    page.select_option(
                        'select[name*="year"], select[id*="year"], select[id*="Year"]',
                        value=year
                    )
                    page.select_option(
                        'select[name*="month"], select[id*="month"], select[id*="Month"]',
                        value=str(int(month))
                    )
                    page.wait_for_load_state('networkidle', timeout=10000)
                else:
                    print(f'[Calendar] 현재 {cur_year}/{cur_month} — 올바른 월')
            except Exception as e:
                print(f'[Calendar] 년/월 확인 건너뜀: {e}')

            # 디버그: 달력 HTML 앞부분
            try:
                cal_html = page.eval_on_selector(
                    'table, .calendar, [class*="cal"]',
                    'el => el.outerHTML'
                )
                print(f'[Calendar DEBUG] {cal_html[:600]}')
            except Exception as e:
                print(f'[Calendar DEBUG] 달력 요소 없음: {e}')
                body_txt = page.inner_text('body')
                print(f'[Calendar DEBUG body] {body_txt[:400]}')

            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        games = _parse_calendar_day(soup, day, date_str)
        print(f'[Calendar] {date_str}: {len(games) if games else 0}경기')
        return games or None

    except Exception as e:
        print(f'[Calendar] 오류: {e}')
        return None


def _parse_calendar_day(soup, day, date_str):
    """
    달력 HTML에서 특정 날짜 셀을 찾아 경기 목록 파싱.

    예상 형식:
      완료: "NC 1:5 LG ①"   →  원정팀 원정점수:홈점수 홈팀 [게임번호]
      취소: "롯데:KT[수원]"  →  원정팀:홈팀[구장] (빨간 텍스트, 스코어 없음)
      예정: "LG 두산"        →  원정팀 홈팀 (스코어 없음)
    """
    target_day = str(day)

    # ── 달력 테이블/컨테이너 탐색 ──
    # id/class 기반 우선 시도
    cal_container = (
        soup.find(id=re.compile(r'cal', re.I)) or
        soup.find(class_=re.compile(r'cal', re.I)) or
        soup.find('table')
    )
    if not cal_container:
        print('[Calendar] 달력 컨테이너 없음')
        return None

    # ── 날짜 셀 탐색 ──
    # 셀 내 첫 번째 숫자 텍스트(날짜)가 target_day와 일치하는 <td> 찾기
    target_td = None
    for td in cal_container.find_all('td'):
        # 셀 내 날짜 숫자 추출: 첫 번째 자식 텍스트 또는 span/a 내 숫자
        day_text = ''
        first_child = next(
            (c for c in td.children if hasattr(c, 'get_text') or isinstance(c, str)),
            None
        )
        if first_child:
            day_text = (
                first_child.get_text(strip=True)
                if hasattr(first_child, 'get_text')
                else str(first_child).strip()
            )
        # 숫자만 있는 경우 날짜로 판단
        if day_text == target_day or (day_text.isdigit() and int(day_text) == day):
            target_td = td
            print(f'[Calendar] {day}일 셀 발견 (첫 텍스트: "{day_text}")')
            break

    # 못 찾으면 텍스트 전체에서 숫자 재탐색
    if not target_td:
        for td in cal_container.find_all('td'):
            texts = [t.strip() for t in td.stripped_strings]
            if texts and texts[0] == target_day:
                target_td = td
                print(f'[Calendar] {day}일 셀 발견 (stripped_strings[0])')
                break

    if not target_td:
        print(f'[Calendar] {day}일 셀을 찾지 못함')
        return None

    # ── 셀 내 경기 항목 파싱 ──
    games = []
    # <li>, <a>, <p>, <span> 등 게임 항목 태그 탐색
    game_items = target_td.find_all(['li', 'a', 'p', 'span'])
    if game_items:
        for item in game_items:
            text = item.get_text(separator=' ', strip=True)
            g = _parse_cal_line(text)
            if g:
                games.append(g)
    else:
        # 태그 없이 텍스트만 있는 경우: 줄바꿈 기반 파싱
        raw = target_td.get_text(separator='\n', strip=True)
        for line in raw.split('\n'):
            line = line.strip()
            if not line or line == target_day:
                continue
            g = _parse_cal_line(line)
            if g:
                games.append(g)

    # 중복 제거 (동일 away+home)
    seen = set()
    unique = []
    for g in games:
        key = (g['away'], g['home'])
        if key not in seen:
            seen.add(key)
            unique.append(g)

    return unique or None


def _parse_cal_line(line):
    """
    달력 한 줄 게임 텍스트 → 게임 dict 또는 None

    패턴:
      완료  : "NC 1 : 5 LG ①"  또는  "NC 1:5 LG"
      취소  : "롯데 : KT [수원]"  또는  "롯데:KT[수원]"
      예정  : "LG 두산"  (팀명 두 개, 스코어 없음)
    """
    line = line.strip()
    # 너무 짧거나 숫자만 있으면 날짜/기타
    if not line or line.isdigit() or len(line) < 3:
        return None

    # ── 완료: 숫자:숫자 포함 ──
    m = re.match(
        r'^(.+?)\s+(\d+)\s*:\s*(\d+)\s+(.+?)(?:\s*[①②③④⑤⑥⑦⑧⑨])?$',
        line
    )
    if m:
        away = normalize_team(m.group(1).strip())
        home = normalize_team(m.group(4).strip())
        if away and home and away in ALL_TEAM_NAMES | {normalize_team(k) for k in TEAM_MAP}:
            return {
                'time':       '',
                'away':       away,
                'home':       home,
                'away_score': m.group(2),
                'home_score': m.group(3),
                'status':     '종료',
                'stadium':    '',
            }

    # ── 취소: [구장] 또는 취소/우천 키워드 포함 (스코어 없음) ──
    if any(k in line for k in ('취소', '우천')) or re.search(r'\[.+\]', line):
        # 팀명 추출: "롯데:KT[수원]" → 롯데, KT
        m2 = re.match(r'^(.+?)\s*[:·]\s*(.+?)(?:\s*\[.*\])?$', line)
        if m2:
            away = normalize_team(m2.group(1).strip())
            home = normalize_team(re.sub(r'\[.*\]', '', m2.group(2)).strip())
            if away and home:
                return {
                    'time':       '',
                    'away':       away,
                    'home':       home,
                    'away_score': None,
                    'home_score': None,
                    'status':     '우천취소',
                    'stadium':    '',
                }

    # ── 예정: 팀명 두 개 (스코어 없음) ──
    # 알려진 팀명으로 분리 시도
    parts = line.split()
    if len(parts) >= 2:
        # 팀명은 1~2 토큰으로 구성
        for split_at in range(1, len(parts)):
            away_try = normalize_team(' '.join(parts[:split_at]))
            home_try = normalize_team(' '.join(parts[split_at:]))
            if away_try != ' '.join(parts[:split_at]) and home_try != ' '.join(parts[split_at:]):
                # 둘 다 TEAM_MAP에서 변환됨
                return {
                    'time':       '',
                    'away':       away_try,
                    'home':       home_try,
                    'away_score': None,
                    'home_score': None,
                    'status':     '예정',
                    'stadium':    '',
                }

    return None


# ── 2) Naver Sports API (폴백) ────────────────────────────────────────────────
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
        try_kbo_calendar(date_str) or
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
