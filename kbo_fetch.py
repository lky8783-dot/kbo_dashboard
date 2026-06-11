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
try:
    import requests as _requests
except ImportError:
    _requests = None

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
    Naver 스포츠 팀순위(teamRank) 우선 스크래핑, 실패 시 KBO 공식 페이지 폴백.
    반환: list of dict {rank, team, gp, w, d, l, pct, gb, last10, streak}
    """
    # 1) Naver 우선
    raw = fetch_naver_records('teamRank')
    if raw and raw.get('rows'):
        standings = _parse_naver_standings(raw)
        if standings:
            print(f'[Standings] Naver 수집 완료: {len(standings)}팀')
            for s in standings:
                print(f'  {s["rank"]}위 {s["team"]}  '
                      f'{s["w"]}승{s["d"]}무{s["l"]}패  '
                      f'승률{s["pct"]}  GB{s["gb"]}  최근10:{s["last10"]}')
            return standings
        print('[Standings] Naver 파싱 실패 — KBO 공식 폴백')
    else:
        print('[Standings] Naver 데이터 없음 — KBO 공식 폴백')

    # 2) 폴백: KBO 공식 페이지
    return _fetch_standings_kbo()


def _parse_naver_standings(raw: dict) -> list:
    """fetch_naver_records('teamRank') 결과 → standings 구조로 변환"""
    headers = raw.get('headers', [])
    rows    = raw.get('rows', [])
    if not headers or not rows:
        return []

    print(f'[Standings] Naver 헤더: {headers}')

    def _ci(names):
        """헤더에서 첫 번째 매칭 컬럼 인덱스 반환 (정확한 일치 우선)"""
        # 1차: 정확한 일치
        for n in names:
            try:
                return headers.index(n)
            except ValueError:
                pass
        # 2차: 부분 일치 폴백 (단, 더 짧은 n이 더 긴 h에 포함될 때만)
        for n in names:
            i = next((j for j, h in enumerate(headers)
                      if n in h and h != n), -1)
            if i >= 0:
                return i
        return -1

    rank_ci   = _ci(['순위'])
    team_ci      = _ci(['팀'])
    gp_ci        = _ci(['경기'])
    w_ci         = _ci(['승'])
    d_ci         = _ci(['무'])
    l_ci         = _ci(['패'])
    pct_ci       = _ci(['승률'])
    gb_ci        = _ci(['게임차'])
    last10_ci    = _ci(['최근'])
    streak_ci    = _ci(['연속'])
    next_opp_ci  = _ci(['다음상대'])
    next_logo_ci = _ci(['상대팀로고'])
    team_logo_ci = _ci(['팀로고'])

    standings = []
    for i, row in enumerate(rows):
        if len(standings) >= 10:
            break  # KBO는 10개 구단
        try:
            if len(row) < 4:
                continue

            def _v(ci, default=''):
                return row[ci] if 0 <= ci < len(row) else default

            def _int(ci):
                return int(re.sub(r'\D', '', _v(ci)) or 0)

            rank_raw = _v(rank_ci)
            rank = int(re.sub(r'\D', '', rank_raw) or 0)
            if rank == 0:
                rank = i + 1  # 인덱스 기반 폴백

            team_raw = _v(team_ci) or row[0]
            team = normalize_team(team_raw) or team_raw

            gp = _int(gp_ci)
            w  = _int(w_ci)
            d  = _int(d_ci)
            l  = _int(l_ci)

            pct_s = _v(pct_ci).replace(',', '.')
            try:
                pct = float(pct_s)
            except Exception:
                pct = w / (w + l) if (w + l) > 0 else 0.0

            gb_raw = _v(gb_ci)
            # 1위(0.0)는 '-'로 표시
            try:
                gb = '-' if float(gb_raw) == 0 else gb_raw
            except Exception:
                gb = gb_raw or '-'

            last10_raw = _v(last10_ci)
            # 'WWLLW' 형식(W/L 문자) → '3승0무2패' 변환
            if last10_raw and re.match(r'^[WLDTwldt]+$', last10_raw):
                uw = last10_raw.upper()
                ww = uw.count('W')
                dd = uw.count('D') + uw.count('T')
                ll = uw.count('L')
                last10 = f'{ww}승{dd}무{ll}패'
            else:
                last10 = last10_raw

            streak_raw = _v(streak_ci)
            # '3W' 또는 '3L' 형식 변환
            if streak_raw and re.match(r'^\d+[WL]$', streak_raw):
                num = streak_raw[:-1]
                ch  = 'W' if streak_raw[-1] == 'W' else 'L'
                streak = f'{num}{"연승" if ch=="W" else "연패"}'
            # '3승' / '3패' 형식 → '3연승' / '3연패'
            elif streak_raw and re.match(r'^\d+[승패무]$', streak_raw):
                num = streak_raw[:-1]
                ch  = streak_raw[-1]
                if ch == '승':
                    streak = f'{num}연승'
                elif ch == '패':
                    streak = f'{num}연패'
                else:
                    streak = streak_raw
            else:
                streak = streak_raw

            next_opp  = normalize_team(_v(next_opp_ci)) or _v(next_opp_ci)
            next_logo = _v(next_logo_ci)
            team_logo = _v(team_logo_ci)

            standings.append({
                'rank':      rank,
                'team':      team,
                'team_logo': team_logo,
                'gp':        gp,
                'w':         w,
                'd':         d,
                'l':         l,
                'pct':       round(pct, 3),
                'gb':        gb,
                'last10':    last10,
                'streak':    streak,
                'next_opp':  next_opp,
                'next_logo': next_logo,
            })
        except Exception as e:
            print(f'[Standings] 행 파싱 오류: {e} — {row[:6]}')
            continue

    return standings


# 팀기록 컬럼 정의 (teamRank API offset 기록 포함)
_TEAM_BAT_COLS  = {'팀','팀로고','타율','득점','타점','타수','홈런','안타',
                   '2루타','3루타','도루','볼넷','사구','삼진','출루율','장타율','OPS'}
_TEAM_PIT_COLS  = {'팀','팀로고','평균자책점','실점','자책점','이닝','피안타','피홈런',
                   '탈삼진','볼넷허용','사구허용','실책','WHIP','QS','세이브','홀드','폭투'}


def _extract_team_batting(raw: dict) -> dict:
    """teamRank raw → 팀 공격기록 (offense* 컬럼만 추출)"""
    headers = raw.get('headers', [])
    rows    = raw.get('rows',    [])
    if not headers or not rows:
        return {}
    keep = [i for i, h in enumerate(headers) if h in _TEAM_BAT_COLS]
    if len(keep) < 3:
        return {}
    return {
        'headers': [headers[i] for i in keep],
        'rows':    [[r[i] if i < len(r) else '' for i in keep] for r in rows],
    }


def _extract_team_pitching(raw: dict) -> dict:
    """teamRank raw → 팀 수비기록 (defense* 컬럼만 추출)"""
    headers = raw.get('headers', [])
    rows    = raw.get('rows',    [])
    if not headers or not rows:
        return {}
    keep = [i for i, h in enumerate(headers) if h in _TEAM_PIT_COLS]
    if len(keep) < 3:
        return {}
    return {
        'headers': [headers[i] for i in keep],
        'rows':    [[r[i] if i < len(r) else '' for i in keep] for r in rows],
    }


def _fetch_standings_kbo() -> list:
    """
    폴백: koreabaseball.com/Record/TeamRank/TeamRankDaily.aspx
    """
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print('[Standings/KBO] playwright/bs4 미설치')
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
            print(f'[Standings/KBO] {url} 로딩 중...')
            page.goto(url, wait_until='networkidle', timeout=30000)
            page.wait_for_timeout(2000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, 'html.parser')
        table = (
            soup.find('table', id=re.compile(r'tblRank', re.I)) or
            soup.find('table', class_=re.compile(r'rank', re.I)) or
            soup.find('table')
        )
        if not table:
            print('[Standings/KBO] 테이블을 찾지 못함')
            return []

        headers = [th.get_text(strip=True) for th in (table.find('thead') or table).find_all('th')]
        print(f'[Standings/KBO] 헤더: {headers}')

        standings = []
        for tr in (table.find('tbody') or table).find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all('td')]
            if len(cells) < 7:
                continue

            def _cell(idx, default=''):
                return cells[idx] if idx < len(cells) else default

            try:
                rank = int(re.sub(r'\D', '', _cell(0)) or 0)
            except Exception:
                continue
            if rank == 0:
                continue

            team_raw = _cell(1)
            team = normalize_team(team_raw) if team_raw else ''
            if not team:
                td_list = tr.find_all('td')
                if len(td_list) > 1:
                    img = td_list[1].find('img')
                    if img:
                        team = normalize_team(img.get('alt', '') or img.get('title', ''))

            try:
                gp = int(_cell(2) or 0)
                w  = int(_cell(3) or 0)
                d  = int(_cell(4) or 0)
                l  = int(_cell(5) or 0)
            except Exception:
                continue

            pct_s = _cell(6).replace(',', '.')
            try:
                pct = float(pct_s)
            except Exception:
                pct = w / (w + l) if (w + l) > 0 else 0.0

            gb         = _cell(7) or '-'
            last10     = _cell(8) if len(cells) > 8 else ''
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

        print(f'[Standings/KBO] {len(standings)}팀 파싱 완료')
        for s in standings:
            print(f'  {s["rank"]}위 {s["team"]}  {s["w"]}승{s["d"]}무{s["l"]}패  '
                  f'승률{s["pct"]}  GB{s["gb"]}')
        return standings

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[Standings/KBO] 오류: {e}')
        return []


# ── Naver 스포츠 기록 스크래핑 ───────────────────────────────────────────────

# API 필드명 → 한글 컬럼명
_NAVER_FIELD_MAP = {
    # 공통
    'playerName': '선수명', 'name': '선수명',
    'teamName': '팀',     'team': '팀', 'teamCode': '팀',
    'gameCount': '경기',  'game': '경기',
    'ranking': '순위',    # hitter/pitcher 기록 순위
    'playerImageUrl':      '선수사진',
    'teamImageUrl':        '팀로고',
    'opposingTeamName':    '다음상대',
    'opposingTeamImageUrl':'상대팀로고',
    # 타자
    'atBat': '타수',         'ab': '타수',
    'hit': '안타',           'h': '안타',
    'doubleHit': '2루타',    'double': '2루타',
    'tripleHit': '3루타',    'triple': '3루타',
    'homeRun': '홈런',       'hr': '홈런',
    'rbi': '타점',
    'run': '득점',           'r': '득점',
    'baseOnBalls': '볼넷',   'bb': '볼넷',
    'strikeOut': '삼진',     'so': '삼진',
    'stolenBase': '도루',    'sb': '도루',
    'battingAvg': '타율',    'seasonAvg': '타율', 'avg': '타율', 'ba': '타율',
    'onBasePct': '출루율',   'obp': '출루율',
    'sluggingPct': '장타율', 'slg': '장타율',
    'ops': 'OPS',
    'war': 'WAR',            'warcalc': 'WAR',
    # ── Naver hitter prefix (hitter* 방식) ──────────────────────────────────
    'hitterHra':       '타율',    'hitterGameCount': '경기',
    'hitterAb':        '타수',    'hitterHit':       '안타',
    'hitterH2':        '2루타',   'hitterH3':        '3루타',
    'hitterHr':        '홈런',    'hitterRbi':       '타점',
    'hitterRun':       '득점',    'hitterSb':        '도루',
    'hitterCs':        '도루실패','hitterBb':        '볼넷',
    'hitterHp':        '사구',    'hitterKk':        '삼진',
    'hitterGd':        '병살타',  'hitterObp':       '출루율',
    'hitterSlg':       '장타율',  'hitterOps':       'OPS',
    'hitterWar':       'WAR',
    # ── Naver pitcher prefix (pitcher* 방식) ────────────────────────────────
    'pitcherEra':      '평균자책점', 'pitcherGameCount': '경기',
    'pitcherW':        '승',         'pitcherL':         '패',
    'pitcherSv':       '세이브',     'pitcherHld':       '홀드',
    'pitcherHold':     '홀드',       'pitcherIp':        '이닝',
    'pitcherPitchedInning': '이닝',  'pitcherHit':       '피안타',
    'pitcherHr':       '피홈런',     'pitcherEr':        '자책점',
    'pitcherBb':       '볼넷',       'pitcherHp':        '사구',
    'pitcherKk':       '탈삼진',     'pitcherRun':       '실점',
    'pitcherWhip':     'WHIP',        'pitcherWar':       'WAR',
    'pitcherQs':       'QS',          'pitcherCg':        '완투',
    'pitcherSho':      '완봉',
    # 투수
    'win': '승',             'wins': '승',
    'lose': '패',            'losses': '패',
    'save': '세이브',        'sv': '세이브',
    'hold': '홀드',          'hld': '홀드',
    'inning': '이닝',        'ip': '이닝', 'pitchedInning': '이닝',
    'hitAllowed': '피안타',
    'homeRunAllowed': '피홈런',
    'walkAllowed': '볼넷',
    'strikeoutCount': '탈삼진', 'k': '탈삼진',
    'earnedRun': '자책점',
    'era': '평균자책점',
    'whip': 'WHIP',
    # 팀 수비 추가
    'runAllowed': '실점',  'runsAllowed': '실점', 'allowedRun': '실점',
    'wildPitch': '폭투',   'wp': '폭투',
    'qualityStart': 'QS',  'qs': 'QS',
    'error': '실책',       'fieldingError': '실책',
    'balk': '보크',
    # 팀순위
    'rank': '순위',
    'winCount': '승',      'loseCount': '패',  'drawCount': '무',
    'winningRate': '승률', 'winRate': '승률',  'pct': '승률',
    'gamesBehind': '게임차', 'gb': '게임차',
    'recentTen': '최근10경기', 'last10': '최근10경기', 'recent10': '최근10경기',
    'streak': '연속', 'continuousResult': '연속',
    # Naver teamRank 실제 필드명
    'winGameCount':         '승',
    'drawnGameCount':       '무',
    'loseGameCount':        '패',
    'gameBehind':           '게임차',
    'wra':                  '승률',
    'continuousGameResult': '연속',
    'lastFiveGames':        '최근5경기',
    # ── 팀 공격 (offense* prefix) ────────────────────────────────────────────
    'offenseHra':  '타율',   'offenseRun':  '득점',  'offenseRbi': '타점',
    'offenseAb':   '타수',   'offenseHr':   '홈런',  'offenseHit': '안타',
    'offenseH2':   '2루타',  'offenseH3':   '3루타', 'offenseSb':  '도루',
    'offenseBb':   '볼넷',   'offenseHp':   '사구',  'offenseBbhp':'볼넷+사구',
    'offenseKk':   '삼진',   'offenseGd':   '병살타','offenseObp': '출루율',
    'offenseSlg':  '장타율', 'offenseOps':  'OPS',
    # ── 팀 수비 (defense* prefix) ────────────────────────────────────────────
    'defenseEra':  '평균자책점', 'defenseR':   '실점',   'defenseEr':   '자책점',
    'defenseInning':'이닝',      'defenseHit': '피안타', 'defenseHr':   '피홈런',
    'defenseKk':   '탈삼진',    'defenseBb':  '볼넷허용','defenseHp':  '사구허용',
    'defenseBbhp': '볼넷+사구허용','defenseErr':'실책',  'defenseWhip': 'WHIP',
    'defenseQs':   'QS',         'defenseSave':'세이브', 'defenseHold': '홀드',
    'defenseWp':   '폭투',
    # ── 투수 개인 기록 추가 필드명 ────────────────────────────────────────────
    'pitcherWin':       '승',          'pitcherLose':     '패',
    'pitcherSave':      '세이브',      'pitcherHold':     '홀드',
    'pitcherInning':    '이닝',        'pitcherR':        '실점',
    'pitcherWra':       '승률',        'pitcherStart':    '선발',
    'pitcherPitchCount':'투구수',
    'pitcherInningKk':  '9이닝K',      'pitcherInningBb': '9이닝BB',
    'pitcherKkBbRate':  'K/BB',        'pitcherPaKkRate': 'K%',
    'pitcherPaBbRate':  'BB%',
}

# 수집 시 완전히 제외할 불필요 필드
_SKIP_FIELDS = frozenset({
    # 신체/개인정보
    'weight', 'height', 'backNumber',
    # Naver 내부 메타
    'isRetire', 'isPlayer', 'osId', 'profile', 'enable',
    'teamId', 'teamShortName', 'seasonId', 'year',
    'upperCategoryId', 'categoryId', 'league', 'division',
    'isQualified', 'isKoreanPlayer',
    # 고급 스탯 (표시 불필요)
    'hitterIsop', 'hitterBabip', 'hitterWoba', 'hitterWrcPlus', 'hitterWpa',
    'pitcherBabip', 'pitcherFip', 'pitcherXfip', 'pitcherWpa',
    # playerId (이미 ranking/순위로 식별)
    'playerId',
    # teamRank 내부 필드 (표시 불필요)
    'wcRanking', 'wcGameBehind', 'gameType', 'orderNo',
    'hasMyTeam', 'myTeamCategoryId', 'nextScheduleGameId',
    'keyword', 'pkId',
    # 투수 고급 지표 (복잡해서 표시 불필요)
    'pitcherKkBbRate', 'pitcherPaKkRate', 'pitcherPaBbRate',
    'pitcherInningKk', 'pitcherInningBb', 'pitcherPitchCount',
})


def _fmt_api_val(v) -> str:
    """API 값 → 표시용 문자열 (None 제거, 긴 소수 정리)"""
    if v is None:
        return ''
    if isinstance(v, float):
        # 소수점 3자리로 반올림 후 Python 기본 표시 (불필요한 trailing 0 없음)
        if abs(v) < 10:
            return str(round(v, 3))
        return str(round(v, 2))
    return str(v)


def _map_field(key: str) -> str:
    """API 필드명 → 표시 컬럼명"""
    return _NAVER_FIELD_MAP.get(key, _NAVER_FIELD_MAP.get(key.lower(), key))


# ── 탭별 기대 스탯 필드 (소문자) ──────────────────────────────────────────────
_STAT_HINTS = {
    'hitter': {
        'battingavg', 'seasonavg', 'avg', 'homerun', 'rbi',
        'ops', 'hit', 'onbasepct', 'sluggingpct', 'stolenbase',
        'strikeout', 'run', 'atbat',
        # Naver hitter prefix (lowercase)
        'hitterhra', 'hitterhit', 'hitterhr', 'hitterrbi',
        'hitterrun', 'hitterops', 'hitterwar', 'hitterab',
        'hittersb', 'hitterkk', 'hitterobp', 'hitterslg',
    },
    'pitcher': {
        'era', 'win', 'lose', 'save', 'whip',
        'strikeoutcount', 'inning', 'hold', 'pitchedinning',
        'earnedrun',
        # Naver pitcher prefix (lowercase)
        'pitchera', 'pitcherw', 'pitchersv', 'pitcherwhip',
        'pitcherkk', 'pitcherwar', 'pitcherip',
    },
    'teamrecord': {
        'battingavg', 'homerun', 'stolenbase',
        'ops', 'onbasepct', 'run', 'hit', 'sluggingpct',
        'rbi', 'atbat', 'double', 'doublehit',
        # Naver offense prefix (lowercase)
        'offensehra', 'offensehr', 'offensehit', 'offenserun',
        'offenseops', 'offensesb', 'offrbi',
    },
    'teampitching': {
        'era', 'whip', 'hitallowed', 'earnedrun',
        'pitchedinning', 'inning', 'strikeoutcount',
        'homerunallowed', 'wildpitch', 'runallowed',
        'qualitystart', 'qs',
        # Naver defense prefix (lowercase)
        'defenseera', 'defensewhip', 'defensekk', 'defenser',
        'defenseqs', 'defensesave',
    },
    'teamrank': {
        'wincount', 'losecount', 'drawcount', 'winningrate',
        'gamesbehind', 'rank', 'recentten', 'streak',
    },
}
# 레지스트리 마커: 이 필드가 있으면 스포츠 팀/선수 목록(통계 아님)
_REGISTRY_MARKERS = frozenset({
    'categoryId', 'categoryName', 'categoryNameEng',
    'categoryCode', 'leagueCode',
})


def _score_candidate(items: list, tab: str) -> int:
    """
    리스트가 해당 탭의 KBO 기록일 가능성 점수.
    음수(-100) → 제외 대상 (레지스트리/무관 데이터).
    """
    if not items or not isinstance(items[0], dict):
        return -100
    sample = items[0]
    sample_keys_lower = {k.lower() for k in sample.keys()}

    # ① 레지스트리 마커 감지
    if set(sample.keys()) & _REGISTRY_MARKERS:
        # categoryId 값이 여러 종목인지 확인
        cats = {str(it.get('categoryId', '')) for it in items[:min(len(items), 15)]}
        non_kbo = cats - {'kbo', '', 'None', 'null'}
        if non_kbo:
            return -100   # 멀티스포츠 레지스트리 → 제외

    # ② 스탯 필드 힌트 매칭
    hints = _STAT_HINTS.get(tab.lower(), set())
    hint_score = sum(1 for h in hints if h in sample_keys_lower)

    # ③ 컬럼 수 (상세할수록 높은 점수)
    col_score = min(len(sample.keys()), 30)

    # ④ 행 수 (팀 탭은 10행, 선수 탭은 50~200행 예상)
    row_cnt = len(items)
    if 'team' in tab.lower():
        # 10개 팀에 가까울수록 보너스
        row_score = max(0, 10 - abs(row_cnt - 10))
    else:
        row_score = min(row_cnt // 20, 5)

    return hint_score * 20 + col_score + row_score


def _find_scored_lists(obj, tab: str, depth=0) -> list:
    """JSON 트리를 재귀 탐색, (score, list) 쌍으로 반환"""
    if depth > 6:
        return []
    results = []
    if isinstance(obj, list):
        if len(obj) >= 3 and all(isinstance(x, dict) for x in obj[:3]):
            score = _score_candidate(obj, tab)
            results.append((score, obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            results.extend(_find_scored_lists(v, tab, depth + 1))
    return results


def _fetch_naver_api_direct(tab: str) -> dict:
    """
    Naver 스포츠 API 직접 호출 (Playwright 없이 requests 사용).
    tab: 'hitter' | 'pitcher' | 'teamRank'
    """
    if _requests is None:
        print(f'[DirectAPI:{tab}] requests 미설치 — 건너뜀')
        return {}
    DIRECT_URLS = {
        'hitter': (
            'https://api-gw.sports.naver.com/statistics/categories/kbo'
            '/seasons/2026/players?playerType=HITTER&limit=50'
        ),
        'pitcher': (
            'https://api-gw.sports.naver.com/statistics/categories/kbo'
            '/seasons/2026/players?playerType=PITCHER&limit=50'
        ),
        'teamRank': (
            'https://api-gw.sports.naver.com/statistics/categories/kbo'
            '/seasons/2026/teams?gameType=REGULAR_SEASON'
        ),
    }
    url = DIRECT_URLS.get(tab)
    if not url:
        return {}
    hdrs = {
        **BASE_HEADERS,
        'Referer': f'https://m.sports.naver.com/kbaseball/record/kbo?seasonCode=2026&tab={tab}',
        'Accept': 'application/json, text/plain, */*',
        'Origin': 'https://m.sports.naver.com',
    }
    try:
        resp = _requests.get(url, headers=hdrs, timeout=15)
        if resp.status_code != 200:
            print(f'[DirectAPI:{tab}] HTTP {resp.status_code}')
            return {}
        body = resp.json()
        scored = _find_scored_lists(body, tab)
        best_score, best_result = -999, {}
        for score, items in sorted(scored, key=lambda x: x[0], reverse=True):
            if score <= 0 or len(items) < 3 or not isinstance(items[0], dict):
                break
            keys = list(items[0].keys())
            if len(keys) < 3:
                continue
            if score > best_score:
                best_score = score
                fkeys = [k for k in keys if k not in _SKIP_FIELDS]
                headers = [_map_field(k) for k in fkeys]
                rows = [[_fmt_api_val(item.get(k)) for k in fkeys] for item in items]
                best_result = {'headers': headers, 'rows': rows}
        if best_result:
            h, r = best_result['headers'], best_result['rows']
            print(f'[DirectAPI:{tab}] 성공(score={best_score}): {len(r)}행 컬럼={h[:6]}')
            return best_result
        print(f'[DirectAPI:{tab}] 데이터 미발견 (score={best_score})')
        return {}
    except Exception as e:
        print(f'[DirectAPI:{tab}] 오류: {e}')
        return {}


def fetch_naver_records(tab: str) -> dict:
    """
    Naver 스포츠 KBO 기록 스크래핑
    1차: 네트워크 JSON API 인터셉트  (React 앱 비동기 로드)
    2차: DOM <table> 파싱 폴백
    tab: 'hitter' | 'pitcher' | 'teamRecord' | 'teamRank'
    Returns: {'headers': [...], 'rows': [[...]...]}
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f'[NaverRec:{tab}] playwright 미설치')
        return {}

    page_url = (
        f'https://m.sports.naver.com/kbaseball/record/kbo'
        f'?seasonCode=2026&tab={tab}'
    )
    captured = []   # (url, json_body)

    def _on_response(resp):
        try:
            if resp.status != 200:
                return
            ct = resp.headers.get('content-type', '')
            if 'json' not in ct:
                return
            u = resp.url
            if 'naver.com' not in u:
                return
            body = resp.json()
            captured.append((u, body))
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
                viewport={'width': 390, 'height': 844},
            )
            page = ctx.new_page()
            page.on('response', _on_response)

            print(f'[NaverRec:{tab}] 로딩 중... {page_url}')
            page.goto(page_url, wait_until='networkidle', timeout=40000)
            page.wait_for_timeout(2000)

            # 스크롤 → 지연 로딩 트리거
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(1500)

            # DOM <table> 폴백용 추출
            dom = page.evaluate("""() => {
                for (const tbl of document.querySelectorAll('table')) {
                    const ths = Array.from(tbl.querySelectorAll('thead th,thead td'))
                        .map(e => e.textContent.trim()).filter(Boolean);
                    const trs = Array.from(tbl.querySelectorAll('tbody tr'))
                        .map(tr => Array.from(tr.querySelectorAll('td,th'))
                            .map(td => td.textContent.trim()))
                        .filter(r => r.length > 2);
                    if (ths.length > 3 && trs.length > 3) {
                        return { ok: true, headers: ths, rows: trs };
                    }
                }
                // 디버그 정보
                return {
                    ok: false,
                    tableCount: document.querySelectorAll('table').length,
                    bodyText: document.body.innerText.slice(0, 600)
                };
            }""")
            browser.close()

        print(f'[NaverRec:{tab}] 인터셉트: {len(captured)}개 API 응답')

        # ── 1) API 인터셉트 결과 파싱 (점수 기반) ─────────────────────────
        # URL 힌트로 1차 정렬 (KBO 스탯 URL 우선)
        URL_HINTS = {
            'hitter':     ['hitter', 'batter', 'batting', 'kbo'],
            'pitcher':    ['pitcher', 'pitching', 'kbo'],
            'teamRecord': ['teamrecord', 'team', 'record', 'kbo'],
            'teamRank':   ['teamrank', 'rank', 'standing', 'kbo'],
        }
        url_hints = URL_HINTS.get(tab, [tab.lower()])
        ordered = sorted(captured,
            key=lambda x: sum(h in x[0].lower() for h in url_hints),
            reverse=True)

        print(f'[NaverRec:{tab}] 캡처 URL 목록:')
        for u, _ in captured:
            print(f'  {u[:100]}')

        best_score, best_result = -999, {}
        for api_url, body in ordered:
            scored = _find_scored_lists(body, tab)
            for score, items in sorted(scored, key=lambda x: x[0], reverse=True):
                if score <= 0:
                    break
                if len(items) < 3 or not isinstance(items[0], dict):
                    continue
                keys = list(items[0].keys())
                if len(keys) < 3:
                    continue
                print(f'[NaverRec:{tab}] 후보: score={score} '
                      f'{len(items)}행 컬럼={[_map_field(k) for k in keys[:6]]} '
                      f'url={api_url[:60]}')
                if score > best_score:
                    best_score = score
                    # _SKIP_FIELDS 제외
                    fkeys = [k for k in keys if k not in _SKIP_FIELDS]
                    headers = [_map_field(k) for k in fkeys]
                    rows    = [[_fmt_api_val(item.get(k)) for k in fkeys]
                               for item in items]
                    best_result = {'headers': headers, 'rows': rows}

        # 탭별 최소 점수 임계값 (낮은 품질 데이터로 덮어쓰기 방지)
        MIN_SCORE = {
            'hitter': 50, 'pitcher': 50,
            'teamRecord': 20, 'teamRank': 15,
        }
        min_s = MIN_SCORE.get(tab, 20)
        if best_result and best_score >= min_s:
            h, r = best_result['headers'], best_result['rows']
            print(f'[NaverRec:{tab}] API 파싱 성공(score={best_score}): '
                  f'{len(r)}행 컬럼={h[:8]}')
            return best_result
        elif best_result:
            print(f'[NaverRec:{tab}] 점수 미달(score={best_score} < {min_s}) — 결과 버림')
            best_result = {}

        # ── 2) DOM <table> 폴백 ────────────────────────────────────────────
        if dom and dom.get('ok'):
            h, r = dom['headers'], dom['rows']
            print(f'[NaverRec:{tab}] DOM 파싱 성공: 헤더={len(h)} 행={len(r)}')
            return {'headers': h, 'rows': r}

        # 실패 진단
        if dom:
            print(f'[NaverRec:{tab}] DOM 테이블 없음 '
                  f'(table 태그:{dom.get("tableCount",0)}개)')
            print(f'[NaverRec:{tab}] 페이지 텍스트: '
                  f'{dom.get("bodyText","")[:300]}')
        print(f'[NaverRec:{tab}] 수집 실패 — 캡처 URL 목록:')
        for u, _ in captured:
            print(f'  {u[:100]}')
        return {}

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[NaverRec:{tab}] 오류: {e}')
        return {}


def fetch_team_records() -> dict:
    """
    팀 공격기록 + 수비기록 모두 수집 (Naver 팀기록 페이지).
    1. ?tab=teamRecord 로드 → 공격기록 API 캡처
    2. "수비기록" 탭 클릭 → 수비기록 API 캡처
    Returns: {'batting': {headers, rows}, 'pitching': {headers, rows}}
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('[TeamRec] playwright 미설치')
        return {}

    page_url = (
        'https://m.sports.naver.com/kbaseball/record/kbo'
        '?seasonCode=2026&tab=teamRecord'
    )
    captured: list = []   # (url, body, phase)
    _phase = ['batting']  # mutable closure

    def _on_response(resp):
        try:
            if resp.status != 200:
                return
            ct = resp.headers.get('content-type', '')
            if 'json' not in ct:
                return
            if 'naver.com' not in resp.url:
                return
            body = resp.json()
            captured.append((resp.url, body, _phase[0]))
        except Exception:
            pass

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
                viewport={'width': 390, 'height': 844},
            )
            page = ctx.new_page()
            page.on('response', _on_response)

            print(f'[TeamRec] 로딩 중... {page_url}')
            page.goto(page_url, wait_until='networkidle', timeout=40000)
            page.wait_for_timeout(2000)
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(1000)

            # 수비기록 탭 클릭 시도
            _phase[0] = 'pitching'
            clicked = False
            for selector in ['text=수비기록', 'button:has-text("수비")',
                              '[class*="tab"]:has-text("수비")',
                              'li:has-text("수비기록")']:
                try:
                    page.click(selector, timeout=4000)
                    page.wait_for_timeout(2500)
                    print(f'[TeamRec] 수비기록 탭 클릭 성공 ({selector})')
                    clicked = True
                    break
                except Exception:
                    pass
            if not clicked:
                print('[TeamRec] 수비기록 탭 클릭 실패 — 공격 데이터만 수집')

            browser.close()

        print(f'[TeamRec] 인터셉트: {len(captured)}개 API 응답')
        for u, _, ph in captured:
            print(f'  [{ph}] {u[:100]}')

        def _extract(hint_tab, phase_filter):
            best_score, best_result = -999, {}
            candidates = [(u, b) for u, b, ph in captured if ph == phase_filter]
            # phase 필터링 후 없으면 전체에서 시도
            if not candidates:
                candidates = [(u, b) for u, b, _ in captured]
            for api_url, body in candidates:
                scored = _find_scored_lists(body, hint_tab)
                for score, items in sorted(scored, key=lambda x: x[0], reverse=True):
                    if score <= 0:
                        break
                    if len(items) < 3 or not isinstance(items[0], dict):
                        continue
                    keys = list(items[0].keys())
                    if len(keys) < 3:
                        continue
                    print(f'[TeamRec:{hint_tab}] 후보 score={score} '
                          f'{len(items)}행 컬럼={[_map_field(k) for k in keys[:6]]} '
                          f'url={api_url[:60]}')
                    if score > best_score:
                        best_score = score
                        fkeys = [k for k in keys if k not in _SKIP_FIELDS]
                        headers = [_map_field(k) for k in fkeys]
                        rows    = [[_fmt_api_val(item.get(k)) for k in fkeys]
                                   for item in items]
                        best_result = {'headers': headers, 'rows': rows}
            if best_result:
                print(f'[TeamRec:{hint_tab}] 선택 score={best_score} '
                      f'{len(best_result["rows"])}행')
            else:
                print(f'[TeamRec:{hint_tab}] 수집 실패')
            return best_result

        batting  = _extract('teamRecord',   'batting')
        pitching = _extract('teamPitching', 'pitching')
        return {'batting': batting, 'pitching': pitching}

    except Exception as e:
        import traceback; traceback.print_exc()
        print(f'[TeamRec] 오류: {e}')
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

    # 팀 순위 수집 (직접 API 우선 → Playwright 폴백)
    raw_teamrank = _fetch_naver_api_direct('teamRank')
    if not (raw_teamrank and raw_teamrank.get('rows')):
        print('[teamRank] 직접 API 실패 → Playwright 시도')
        raw_teamrank = fetch_naver_records('teamRank')
    standings       = (_parse_naver_standings(raw_teamrank)
                       if raw_teamrank and raw_teamrank.get('rows') else [])
    if standings:
        print(f'[Standings] Naver 파싱: {len(standings)}팀')
    else:
        print('[Standings] Naver 파싱 실패 → KBO 공식 폴백')
        standings = _fetch_standings_kbo()

    # teamRank 응답에서 팀 공격/수비 기록 추출 (별도 fetch 불필요)
    team_batting  = _extract_team_batting(raw_teamrank  or {})
    team_pitching = _extract_team_pitching(raw_teamrank or {})
    if not team_batting.get('rows') or not team_pitching.get('rows'):
        print('[TeamRec] teamRank에서 팀기록 미추출 → 별도 fetch 시도')
        team_recs     = fetch_team_records()
        team_batting  = team_batting  or team_recs.get('batting',  {})
        team_pitching = team_pitching or team_recs.get('pitching', {})

    # 타자/투수 개인 기록 수집 (직접 API 우선 → Playwright 폴백 → 기존 보존)
    _is_good = lambda rec: bool(rec and rec.get('rows') and len(rec.get('rows',[])) >= 10)
    prev_hitter  = existing.get('hitter_records',  {})
    prev_pitcher = existing.get('pitcher_records', {})

    hitter_records  = _fetch_naver_api_direct('hitter')
    if not _is_good(hitter_records):
        print('[hitter] 직접 API 실패 → Playwright 시도')
        hitter_records = fetch_naver_records('hitter')
    if not _is_good(hitter_records) and _is_good(prev_hitter):
        print(f'[hitter] 새 데이터 품질 미달 → 기존 {len(prev_hitter["rows"])}행 유지')
        hitter_records = prev_hitter

    pitcher_records = _fetch_naver_api_direct('pitcher')
    if not _is_good(pitcher_records):
        print('[pitcher] 직접 API 실패 → Playwright 시도')
        pitcher_records = fetch_naver_records('pitcher')
    if not _is_good(pitcher_records) and _is_good(prev_pitcher):
        print(f'[pitcher] 새 데이터 품질 미달 → 기존 {len(prev_pitcher["rows"])}행 유지')
        pitcher_records = prev_pitcher

    result = {
        'updated':              today.strftime('%Y-%m-%dT%H:%M:%S'),
        'today':                today.strftime('%Y-%m-%d'),
        'dates':                dates_data,
        'standings':            standings,
        'standings_updated':    today.strftime('%Y-%m-%d'),
        'hitter_records':       hitter_records,
        'pitcher_records':      pitcher_records,
        'team_records':         team_batting,   # 하위 호환
        'team_batting_records': team_batting,
        'team_pitch_records':   team_pitching,
        'records_updated':      today.strftime('%Y-%m-%d'),
    }

    with open('kbo_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(v['games']) for v in dates_data.values())
    print(f'저장 완료: kbo_data.json ({len(dates_data)}일, {total}경기, 순위 {len(standings)}팀)')


if __name__ == '__main__':
    main()
