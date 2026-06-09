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


KNOWN_TEAMS = set(TEAM_MAP.values())


def _is_team(name):
    """정규화 후 알려진 팀명인지 확인"""
    return normalize_team(name) in KNOWN_TEAMS


def _parse_cal_line(line):
    """
    달력 한 줄 게임 텍스트 → 게임 dict 또는 None

    koreabaseball.com 달력 실제 형식:
      완료  : "KT 6:0 두산"  또는  "KT 6:0 두산 ①"
      예정  : "LG : 두산"    (콜론 양쪽 공백, 숫자 없음)
      취소  : "롯데:KT[수원]" (대괄호 구장 또는 취소 키워드)
    """
    line = line.strip()
    if not line or line.isdigit() or len(line) < 3:
        return None

    # ── 1) 완료: "팀A 점수:점수 팀B [①]" ──
    m = re.match(
        r'^(.+?)\s+(\d+)\s*:\s*(\d+)\s+(.+?)(?:\s*[①②③④⑤⑥⑦⑧⑨])?$',
        line
    )
    if m:
        away = normalize_team(m.group(1).strip())
        home = normalize_team(m.group(4).strip())
        if away in KNOWN_TEAMS and home in KNOWN_TEAMS:
            return {
                'time':       '',
                'away':       away,
                'home':       home,
                'away_score': m.group(2),
                'home_score': m.group(3),
                'status':     '종료',
                'stadium':    '',
            }

    # ── 2) 취소: [구장] 또는 취소/우천 키워드 ──
    if any(k in line for k in ('취소', '우천')) or re.search(r'\[.+\]', line):
        m2 = re.match(r'^(.+?)\s*[:·]\s*(.+?)(?:\s*\[.*\])?$', line)
        if m2:
            away = normalize_team(m2.group(1).strip())
            home = normalize_team(re.sub(r'\[.*\]', '', m2.group(2)).strip())
            if away in KNOWN_TEAMS and home in KNOWN_TEAMS:
                return {
                    'time':       '',
                    'away':       away,
                    'home':       home,
                    'away_score': None,
                    'home_score': None,
                    'status':     '우천취소',
                    'stadium':    '',
                }

    # ── 3) 예정: "팀A : 팀B" (콜론 구분, 숫자 없음) ──
    if ':' in line and not re.search(r'\d+\s*:\s*\d+', line):
        m3 = re.match(r'^(.+?)\s*:\s*(.+?)(?:\s*[①②③④⑤])?$', line)
        if m3:
            away = normalize_team(m3.group(1).strip())
            home = normalize_team(m3.group(2).strip())
            if away in KNOWN_TEAMS and home in KNOWN_TEAMS:
                return {
                    'time':       '',
                    'away':       away,
                    'home':       home,
                    'away_score': None,
                    'home_score': None,
                    'status':     '예정',
                    'stadium':    '',
                }

    return None


# ── 2) 게임센터 선발투수 ─────────────────────────────────────────────────────
def fetch_pitchers(date_str):
    """
    koreabaseball.com 게임센터에서 선발투수 수집.
    반환: { (away팀명, home팀명): {'away': 투수명, 'home': 투수명} }

    HTML 구조:
      li.game-cont > .team.away > .emb > img[alt=팀코드]
                                > .today-pitcher > p > span.before(선) + 투수명
      li.game-cont > .team.home > ...
    """
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        return {}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'], locale='ko-KR'
            )
            page = ctx.new_page()
            url = (f'https://www.koreabaseball.com/Schedule/GameCenter/Main.aspx'
                   f'?gameDate={date_str}')
            print(f'[Pitcher] {url}')
            page.goto(url, wait_until='networkidle', timeout=30000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        result = _parse_pitchers(soup)
        print(f'[Pitcher] {date_str}: {len(result)}경기 선발투수 수집')
        return result

    except Exception as e:
        print(f'[Pitcher] 오류: {e}')
        return {}


GC_STATUS_MAP = {
    '경기예정': '예정',
    '경기중':   '진행 중',
    '경기종료': '종료',
    '우천취소': '우천취소',
    '취소':     '취소',
}


def _parse_pitchers(soup):
    """
    li.game-cont 구조에서 선발투수 + 경기 메타(상태·시간·구장·스코어) 추출.
    반환: { (away팀명, home팀명): {
        'away': 투수명, 'home': 투수명,
        'status': '예정'|'진행 중'|'종료'|...,
        'time': '18:30',
        'stadium': '잠실야구장',
        'away_score': '3' or None,
        'home_score': '1' or None,
    }}
    """
    result = {}

    def pitcher_name(team_div):
        """today-pitcher div에서 투수명 추출 (span.before '선' 제거)"""
        p_div = team_div.find('div', class_='today-pitcher')
        if not p_div:
            return ''
        p_tag = p_div.find('p')
        if not p_tag:
            return p_div.get_text(strip=True).lstrip('선')
        for span in p_tag.find_all('span', class_='before'):
            span.decompose()
        return p_tag.get_text(strip=True)

    def extract_score(team_div, li_el):
        """
        팀 div(또는 li 전체)에서 스코어 숫자 추출.
        KBO 게임센터 HTML은 버전마다 구조가 다르므로 여러 셀렉터를 순서대로 시도.
        """
        # 1) 팀 div 내 .score / em / strong / span 숫자
        for sel in ['.score em', 'em.score', 'span.score', 'strong.score',
                    '.score', 'em', 'strong']:
            el = team_div.select_one(sel)
            if el:
                t = el.get_text(strip=True)
                if t.isdigit():
                    return t
        return None

    for li in soup.find_all('li', class_='game-cont'):
        away_div = li.select_one('.team.away')
        home_div = li.select_one('.team.home')
        if not away_div or not home_div:
            continue

        away_img  = away_div.select_one('.emb img')
        home_img  = home_div.select_one('.emb img')
        away_code = away_img.get('alt', '').strip() if away_img else ''
        home_code = home_img.get('alt', '').strip() if home_img else ''

        away_team = normalize_team(away_code)
        home_team = normalize_team(home_code)
        if not away_team or not home_team:
            continue

        away_p = pitcher_name(away_div)
        home_p = pitcher_name(home_div)

        # 경기 상태: <p class="staus">경기예정</p>  (KBO HTML 오타 "staus")
        staus_el = li.select_one('p.staus, p.status')
        raw_status = staus_el.get_text(strip=True) if staus_el else ''
        status = GC_STATUS_MAP.get(raw_status, raw_status or '예정')

        # 경기 시간·구장: div.top > ul > li 순서: [구장, 날씨img, 시간]
        top_lis = li.select('div.top ul li')
        stadium_raw = top_lis[0].get_text(strip=True) if len(top_lis) > 0 else ''
        time_str    = top_lis[2].get_text(strip=True) if len(top_lis) > 2 else ''
        stadium     = normalize_stadium(stadium_raw)

        # 중계 방송사: div.middle > div.broadcasting
        bc_el = li.select_one('div.middle div.broadcasting, div.broadcasting')
        broadcaster = bc_el.get_text(strip=True) if bc_el else ''

        # ── 스코어 추출 (경기 중·종료 시) ──────────────────────────────────
        away_score = None
        home_score = None

        if status in ('진행 중', '종료'):
            # 방법 1: 팀 div에서 직접 추출
            away_score = extract_score(away_div, li)
            home_score = extract_score(home_div, li)

            # 방법 2: li 전체에서 숫자쌍 탐색 (방법1 실패 시)
            if away_score is None or home_score is None:
                # score-board, result-score, .score 등 중앙 영역
                for sb_sel in ['.score-board', '.result-score', '.scoreboard',
                                'div.middle', 'div.score']:
                    sb = li.select_one(sb_sel)
                    if sb:
                        nums = [
                            el.get_text(strip=True)
                            for el in sb.find_all(['em', 'span', 'strong', 'b'])
                            if el.get_text(strip=True).isdigit()
                        ]
                        if len(nums) >= 2:
                            away_score, home_score = nums[0], nums[1]
                            break

            # 방법 3: li 전체 텍스트에서 "숫자 : 숫자" 패턴
            # (야구 점수는 보통 0~20 — 18:30 같은 시간 형식 제외)
            if away_score is None or home_score is None:
                li_text = li.get_text(separator=' ')
                for m in re.finditer(r'\b(\d{1,2})\s*:\s*(\d{1,2})\b', li_text):
                    a_n, h_n = int(m.group(1)), int(m.group(2))
                    if a_n <= 20 and h_n <= 20:   # 시간(18:30 등) 제외
                        away_score, home_score = str(a_n), str(h_n)
                        break

        print(f'[Pitcher]  {away_team} vs {home_team}  [{status} {time_str}]'
              f'  score={away_score}:{home_score}  중계:{broadcaster}')

        # 디버그: 스코어를 못 찾았을 때 li HTML 앞부분 출력
        if status in ('진행 중', '종료') and away_score is None:
            print(f'[Pitcher WARN] 스코어 미수집 — li HTML: {str(li)[:400]}')

        result[(away_team, home_team)] = {
            'away':        away_p,
            'home':        home_p,
            'status':      status,
            'time':        time_str,
            'stadium':     stadium,
            'broadcaster': broadcaster,
            'away_score':  away_score,
            'home_score':  home_score,
        }

    return result


# ── 3) Naver Sports API (폴백) ────────────────────────────────────────────────
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


# ── 팀 순위 스크래핑 ──────────────────────────────────────────────────────────
def fetch_standings():
    """
    koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx
    → 팀 순위 테이블 파싱
    반환: list of dict {rank, team, gp, w, d, l, pct, gb, last10, streak}
    """
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print('[Standings] playwright/bs4 미설치')
        return []

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
            )
            page = ctx.new_page()
            url = 'https://www.koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx'
            print(f'[Standings] {url} 로딩 중...')
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')

        # 순위 테이블 탐색
        table = (
            soup.find('table', id=re.compile(r'tblRank', re.I)) or
            soup.find('table', class_=re.compile(r'rank', re.I)) or
            soup.find('table')
        )
        if not table:
            print('[Standings] 테이블을 찾지 못함')
            return []

        # 헤더 파싱
        headers = []
        thead = table.find('thead') or table
        for th in thead.find_all('th'):
            headers.append(th.get_text(strip=True))
        print(f'[Standings] 헤더: {headers}')

        # 행 파싱
        standings = []
        tbody = table.find('tbody') or table
        for tr in tbody.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all('td')]
            if len(cells) < 7:
                continue

            # 헤더 기반 파싱 (순위/팀/경기/승/무/패/승률/게임차/...)
            def _cell(idx, default=''):
                return cells[idx] if idx < len(cells) else default

            # 순위
            try:
                rank = int(re.sub(r'\D', '', _cell(0)) or 0)
            except Exception:
                continue
            if rank == 0:
                continue

            # 팀명
            team_raw = _cell(1)
            team = normalize_team(team_raw) if team_raw else ''
            if not team:
                # 이미지 alt 탐색
                td_team = tr.find_all('td')[1] if len(tr.find_all('td')) > 1 else None
                if td_team:
                    img = td_team.find('img')
                    if img:
                        team = normalize_team(img.get('alt', '') or img.get('title', ''))

            try:
                gp  = int(_cell(2)  or 0)
                w   = int(_cell(3)  or 0)
                d   = int(_cell(4)  or 0)   # 무승부
                l   = int(_cell(5)  or 0)
            except Exception:
                continue

            pct_s = _cell(6).replace(',', '.')
            try:
                pct = float(pct_s)
            except Exception:
                pct = w / (w + l) if (w + l) > 0 else 0.0

            gb_s = _cell(7)
            gb = gb_s if gb_s else '-'

            # 최근 10경기 (있으면)
            last10 = _cell(8) if len(cells) > 8 else ''
            # 연속 (있으면)
            streak_raw = _cell(9) if len(cells) > 9 else ''

            standings.append({
                'rank':   rank,
                'team':   team or team_raw,
                'gp':     gp,
                'w':      w,
                'd':      d,
                'l':      l,
                'pct':    round(pct, 3),
                'gb':     gb,
                'last10': last10,
                'streak': streak_raw,
            })

        print(f'[Standings] {len(standings)}팀 파싱 완료')
        for s in standings:
            print(f'  {s["rank"]}위 {s["team"]}  {s["w"]}승{s["d"]}무{s["l"]}패  승률{s["pct"]}  GB{s["gb"]}')
        return standings

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[Standings] 오류: {e}')
        return []


# ── Naver 스포츠 기록 스크래핑 ───────────────────────────────────────────────
def fetch_naver_records(tab: str) -> dict:
    """
    Naver 스포츠 KBO 기록 스크래핑
    tab: 'hitter' | 'pitcher' | 'teamRecord'
    Returns: {'headers': [...], 'rows': [[...]...]}
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f'[NaverRec:{tab}] playwright 미설치')
        return {}

    url = f'https://m.sports.naver.com/kbaseball/record/kbo?seasonCode=2026&tab={tab}'

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
                viewport={'width': 390, 'height': 844},
            )
            page = ctx.new_page()
            print(f'[NaverRec:{tab}] 로딩 중... {url}')
            page.goto(url, wait_until='networkidle', timeout=30000)
            try:
                page.wait_for_selector('table', timeout=10000)
            except Exception:
                print(f'[NaverRec:{tab}] table 대기 타임아웃 — 계속 진행')
            page.wait_for_timeout(1500)

            result = page.evaluate("""() => {
                const table = document.querySelector('table');
                if (!table) return null;
                const headers = Array.from(table.querySelectorAll('thead th, thead td'))
                    .map(el => el.textContent.trim()).filter(Boolean);
                const rows = Array.from(table.querySelectorAll('tbody tr'))
                    .map(tr => Array.from(tr.querySelectorAll('td, th'))
                        .map(td => td.textContent.trim()));
                return { headers, rows: rows.filter(r => r.length > 2) };
            }""")
            browser.close()

        if not result or not result.get('rows'):
            print(f'[NaverRec:{tab}] 데이터 없음 (테이블 미확인)')
            return {}

        print(f'[NaverRec:{tab}] 헤더:{len(result["headers"])} 행:{len(result["rows"])}')
        for r in result['rows'][:3]:
            print(f'  {r[:8]}')
        return result

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[NaverRec:{tab}] 오류: {e}')
        return {}


# ── Main ──────────────────────────────────────────────────────────────────────

def fetch_day(date_str):
    games = (
        try_kbo_calendar(date_str) or
        try_naver(date_str) or
        []
    )
    # 오늘 날짜: 게임센터에서 선발투수 + 경기 상태(가장 최신) 갱신
    if date_str == datetime.now().strftime('%Y%m%d'):
        try:
            gc_data = fetch_pitchers(date_str)
            if gc_data:
                # 게임센터 데이터를 기존 games에 머지
                # (away, home) 키로 매칭 — 없으면 새 엔트리로 추가
                existing_keys = {(g.get('away', ''), g.get('home', '')): i for i, g in enumerate(games)}
                for (away_t, home_t), info in gc_data.items():
                    idx = existing_keys.get((away_t, home_t))
                    if idx is not None:
                        g = games[idx]
                        # 게임센터 상태를 우선 적용 (더 실시간)
                        g['status']       = info['status']
                        if info['time']:    g['time']    = info['time']
                        if info['stadium']: g['stadium'] = info['stadium']
                        if info['away']:    g['away_pitcher'] = info['away']
                        if info['home']:    g['home_pitcher'] = info['home']
                        if info.get('broadcaster'): g['broadcaster'] = info['broadcaster']
                        # 스코어 업데이트 (경기 중·종료 시 게임센터 값 우선)
                        if info.get('away_score') is not None:
                            g['away_score'] = info['away_score']
                        if info.get('home_score') is not None:
                            g['home_score'] = info['home_score']
                    else:
                        # 게임센터에만 있는 경기 (calendar에서 누락)
                        games.append({
                            'time':         info['time'],
                            'away':         away_t,
                            'home':         home_t,
                            'away_score':   info.get('away_score'),
                            'home_score':   info.get('home_score'),
                            'status':       info['status'],
                            'stadium':      info['stadium'],
                            'away_pitcher': info['away'],
                            'home_pitcher': info['home'],
                            'broadcaster':  info.get('broadcaster', ''),
                        })
        except Exception as e:
            print(f'[Pitcher] 머지 실패: {e}')
    return games


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

    # 시즌 시작일 이후 모든 날짜 보존 (달력·순위표에 필요)
    SEASON_START = '2026-03-01'
    keep       = sorted([k for k in dates_data if k >= SEASON_START], reverse=True)
    dates_data = {k: dates_data[k] for k in keep}

    # 팀 순위 수집
    standings = fetch_standings()

    # 타자/투수/팀 기록 수집
    hitter_records  = fetch_naver_records('hitter')
    pitcher_records = fetch_naver_records('pitcher')
    team_records    = fetch_naver_records('teamRecord')

    result = {
        'updated':            today.strftime('%Y-%m-%dT%H:%M:%S'),
        'today':              today.strftime('%Y-%m-%d'),
        'dates':              dates_data,
        'standings':          standings,
        'standings_updated':  today.strftime('%Y-%m-%d'),
        'hitter_records':     hitter_records,
        'pitcher_records':    pitcher_records,
        'team_records':       team_records,
        'records_updated':    today.strftime('%Y-%m-%d'),
    }

    with open('kbo_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(v['games']) for v in dates_data.values())
    print(f'저장 완료: kbo_data.json ({len(dates_data)}일, {total}경기, 순위 {len(standings)}팀)')


if __name__ == '__main__':
    main()
