#!/usr/bin/env python3
"""
KBO 월별 일괄 수집기 — 달력 뷰 한 번 로드로 한 달 전체 파싱
Usage: python bulk_fetch.py
Output: kbo_data.json  (7일 제한 없이 전체 날짜 보존)
"""

import json
import re
import calendar
from datetime import datetime, date

# kbo_fetch 헬퍼 재사용
from kbo_fetch import BASE_HEADERS, _parse_cal_line, try_naver

TARGET_MONTHS = [
    ('2026', '03'),
    ('2026', '04'),
    ('2026', '05'),
]


# ── 달력 한 달 전체 수집 ──────────────────────────────────────────────────────
def fetch_month_calendar(year: str, month: str) -> dict:
    """
    Playwright로 달력 탭을 열고 해당 월 전체 날짜 셀을 파싱.
    반환: {'YYYY-MM-DD': [game, ...], ...}
    """
    try:
        from playwright.sync_api import sync_playwright
        from bs4 import BeautifulSoup
    except ImportError:
        print('[Bulk] playwright / bs4 미설치')
        return {}

    year_i  = int(year)
    month_i = int(month)
    first_ds = f'{year}{month}01'

    print(f'\n[Bulk] ── {year_i}년 {month_i}월 달력 로딩 ──')

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
            ctx  = browser.new_context(
                user_agent=BASE_HEADERS['User-Agent'],
                locale='ko-KR',
            )
            page = ctx.new_page()

            url = (
                'https://www.koreabaseball.com/Schedule/Schedule.aspx'
                f'?seriesId=0&teamId=0&gameDate={first_ds}'
            )
            page.goto(url, wait_until='networkidle', timeout=30000)

            # 달력 탭 클릭
            try:
                page.click('text=달력', timeout=5000)
                page.wait_for_load_state('networkidle', timeout=15000)
                print(f'[Bulk] 달력 탭 클릭 완료')
            except Exception as e:
                print(f'[Bulk] 달력 탭 클릭 실패: {e}')

            # 년/월 드롭다운 조정 (현재 월이 아닐 경우)
            _set_year_month(page, year, str(month_i))

            # 디버그: 달력 첫 500자
            try:
                cal_el  = page.query_selector('table, [id*="cal"], [class*="cal"]')
                cal_txt = cal_el.inner_text() if cal_el else ''
                print(f'[Bulk DEBUG] 달력 텍스트 앞부분:\n{cal_txt[:400]}')
            except Exception as e:
                print(f'[Bulk DEBUG] {e}')

            html = page.content()
            browser.close()

        soup    = BeautifulSoup(html, 'html.parser')
        results = _parse_all_days(soup, year_i, month_i)
        print(f'[Bulk] {year_i}년 {month_i}월: {len(results)}일 / '
              f'{sum(len(v) for v in results.values())}경기 파싱 완료')
        return results

    except Exception as e:
        print(f'[Bulk] {year}/{month} Playwright 오류: {e}')
        return {}


def _set_year_month(page, year: str, month_str: str):
    """달력 년/월 select 값 맞추기 (JavaScript 직접 제어)"""
    month_i = int(month_str)

    js = f"""
    (function() {{
        // 년도 select
        var ySel = document.querySelector('#ddlYear, select[name*="Year"], select[id*="year"]');
        if (ySel) {{
            for (var i = 0; i < ySel.options.length; i++) {{
                if (ySel.options[i].value == '{year}' || ySel.options[i].text.includes('{year}')) {{
                    ySel.selectedIndex = i;
                    ySel.dispatchEvent(new Event('change', {{bubbles:true}}));
                    break;
                }}
            }}
        }}
        // 월 select
        var mSel = document.querySelector('#ddlMonth, select[name*="Month"], select[id*="month"]');
        if (mSel) {{
            for (var i = 0; i < mSel.options.length; i++) {{
                var v = mSel.options[i].value;
                var t = mSel.options[i].text;
                if (v == '{month_i}' || v == '{month_i:02d}' || t.includes('{month_i}월')) {{
                    mSel.selectedIndex = i;
                    mSel.dispatchEvent(new Event('change', {{bubbles:true}}));
                    break;
                }}
            }}
        }}
        // 옵션 목록 디버그 반환
        return mSel ? Array.from(mSel.options).map(o => o.value+'='+o.text) : [];
    }})()
    """
    try:
        opts = page.evaluate(js)
        print(f'[Bulk] ddlMonth 옵션: {opts[:6]}')
        page.wait_for_load_state('networkidle', timeout=10000)
    except Exception as e:
        print(f'[Bulk] 년/월 JS 오류: {e}')


# ── 달력 HTML 전체 날짜 셀 파싱 ──────────────────────────────────────────────
def _parse_all_days(soup, year: int, month: int) -> dict:
    """
    달력 HTML의 모든 <td> 셀에서 날짜와 경기 목록 추출.
    반환: {'YYYY-MM-DD': [game, ...]}
    """
    results = {}
    max_day = calendar.monthrange(year, month)[1]

    # 달력 컨테이너
    cal = (
        soup.find(id=re.compile(r'cal', re.I))   or
        soup.find(class_=re.compile(r'cal', re.I)) or
        soup.find('table')
    )
    if not cal:
        print('[Bulk] 달력 컨테이너 없음')
        return results

    for td in cal.find_all('td'):
        # ── 날짜 숫자 추출 ──
        day_num = _cell_day_number(td, max_day)
        if day_num is None:
            continue

        date_key = f'{year}-{month:02d}-{day_num:02d}'

        # 미래 날짜는 오늘까지만 (예정 경기도 수집)
        # 필요시 아래 주석 해제:
        # if date(year, month, day_num) > date.today():
        #     continue

        games = _extract_games_from_td(td, day_num)
        if games:
            results[date_key] = games

    return results


def _cell_day_number(td, max_day: int):
    """td 셀에서 날짜 숫자 추출 (없거나 범위 밖이면 None)"""
    texts = [t.strip() for t in td.stripped_strings]
    if not texts:
        return None
    first = texts[0]
    if first.isdigit():
        n = int(first)
        if 1 <= n <= max_day:
            return n
    return None


def _extract_games_from_td(td, day_num: int) -> list:
    """td 셀에서 경기 목록 추출 및 중복 제거"""
    games = []

    # <li>, <a>, <p> 태그 우선
    items = td.find_all(['li', 'a', 'p'])
    if items:
        for item in items:
            text = item.get_text(separator=' ', strip=True)
            g = _parse_cal_line(text)
            if g:
                games.append(g)
    else:
        # 태그 없이 텍스트만 있는 경우
        raw = td.get_text(separator='\n', strip=True)
        for line in raw.split('\n'):
            line = line.strip()
            if not line or line == str(day_num) or line.isdigit():
                continue
            g = _parse_cal_line(line)
            if g:
                games.append(g)

    # 중복 제거 (away+home 기준)
    seen, unique = set(), []
    for g in games:
        k = (g['away'], g['home'])
        if k not in seen:
            seen.add(k)
            unique.append(g)
    return unique


# ── Naver 폴백 (월 단위) ─────────────────────────────────────────────────────
def fetch_month_naver(year: str, month: str) -> dict:
    """Naver API로 한 달치 날짜별 경기 수집 (폴백)"""
    year_i, month_i = int(year), int(month)
    results = {}
    max_day = calendar.monthrange(year_i, month_i)[1]
    today   = date.today()

    print(f'[Bulk/Naver] {year_i}년 {month_i}월 Naver 폴백 시작...')
    for day in range(1, max_day + 1):
        d = date(year_i, month_i, day)
        if d > today:
            break
        ds = d.strftime('%Y%m%d')
        games = try_naver(ds)
        if games:
            results[d.strftime('%Y-%m-%d')] = games

    print(f'[Bulk/Naver] {year_i}년 {month_i}월: {len(results)}일 수집')
    return results


# ── 메인 ─────────────────────────────────────────────────────────────────────
def bulk_main():
    all_dates = {}

    for year, month in TARGET_MONTHS:
        month_data = fetch_month_calendar(year, month)

        if not month_data:
            print(f'[Bulk] 달력 실패 → Naver 폴백')
            month_data = fetch_month_naver(year, month)

        for date_key, games in month_data.items():
            all_dates[date_key] = {'date': date_key, 'games': games}

    # 기존 kbo_data.json 병합 (bulk 데이터 우선)
    try:
        with open('kbo_data.json', 'r', encoding='utf-8') as f:
            existing = json.load(f)
        existing_dates = existing.get('dates', {})
    except Exception:
        existing_dates = {}

    existing_dates.update(all_dates)

    now    = datetime.now()
    result = {
        'updated': now.strftime('%Y-%m-%dT%H:%M:%S'),
        'today':   now.strftime('%Y-%m-%d'),
        'dates':   existing_dates,   # 7일 제한 없이 전체 보존
    }

    with open('kbo_data.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(v['games']) for v in existing_dates.values())
    print(f'\n저장 완료: kbo_data.json ({len(existing_dates)}일, {total}경기)')


if __name__ == '__main__':
    bulk_main()
