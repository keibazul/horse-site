"""한국마사회 경주성적정보(API214_1) 수집 - 서울 경마
(경주 거리, 레이팅, 날씨, 주로, 장구, 구간기록, 단·연승 배당 등 경주·말별 상세 성적)

사용 예 (PowerShell, 먼저 $env:KRA_API_KEY="발급받은Encoding키")
  # 1) 하루치만 받아서 응답 모양 확인 (race_details_probe_날짜.csv 로 저장)
  py -3.13 fetch_race_details.py --probe 20261031

  # 2) merged.csv 의 첫 경주일(2000-01-08) ~ 마지막 경주일까지, 경마가 열린 날만 받기 (이어받기 지원)
  py -3.13 fetch_race_details.py

  # 기간 지정
  py -3.13 fetch_race_details.py --start 20230101 --end 20261031

저장: race_details/rd_날짜.csv (하루 1파일, 응답 항목을 그대로 저장). 이미 받은 날짜는 건너뜁니다.
멈추고 싶으면 race_details 폴더에 STOP 이라는 빈 파일을 만들거나 Ctrl+C (받던 날짜는 다음에 다시 받음).
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

import pandas as pd
import requests

API_URL = "https://apis.data.go.kr/B551015/API214_1/RaceDetailResult_1"
OUT_DIR = "race_details"
USAGE_FILE = os.path.join(OUT_DIR, "daily_usage.json")
STOP_FILE = os.path.join(OUT_DIR, "STOP")
NUM_ROWS = 1000
SLEEP_SEC = 0.2


class LimitReached(Exception):
    pass


class Usage:
    """오늘 보낸 요청 수를 파일에 기록해서 하루 한도를 넘지 않게 함"""

    def __init__(self, limit):
        self.limit = limit
        self.date = datetime.now().strftime("%Y-%m-%d")
        self.count = 0
        if os.path.exists(USAGE_FILE):
            try:
                saved = json.load(open(USAGE_FILE, encoding="utf-8"))
                if saved.get("date") == self.date:
                    self.count = int(saved.get("count", 0))
            except (ValueError, OSError):
                pass

    def add(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self.date:
            self.date, self.count = today, 0
        if self.count >= self.limit:
            raise LimitReached()
        self.count += 1
        with open(USAGE_FILE, "w", encoding="utf-8") as f:
            json.dump({"date": self.date, "count": self.count}, f)


def fetch_day(date, key, usage, session, verbose=False):
    """그날 서울 경마 전 경주·전 출주마의 상세 성적을 받아 표로 돌려줌"""
    rows, page = [], 1
    while True:
        usage.add()
        url = f"{API_URL}?serviceKey={key}&pageNo={page}&numOfRows={NUM_ROWS}&meet=1&rc_date={date}&_type=json"
        res = None
        for attempt in range(3):
            try:
                res = session.get(url, timeout=30)
                res.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 2:
                    raise RuntimeError(f"접속 실패: {e}")
                time.sleep(2)
        try:
            data = res.json()
        except ValueError:
            raise RuntimeError(f"응답이 JSON이 아닙니다 (인증키/활용신청 승인을 확인하세요): {res.text[:300]}")
        resp = data.get("response", data)
        header = resp.get("header", {})
        body = resp.get("body", {}) or {}
        code = str(header.get("resultCode", "00"))
        if verbose:
            print(f"  [{page}페이지] resultCode={code} resultMsg={header.get('resultMsg')} totalCount={body.get('totalCount')}")
        if code not in ("00", "03"):
            raise RuntimeError(f"API 오류 {code}: {header.get('resultMsg')}")
        items = body.get("items")
        if not items:
            break
        item = items["item"] if isinstance(items, dict) else items
        got = [item] if isinstance(item, dict) else list(item)
        if not got:
            break
        rows += got
        total = int(body.get("totalCount", 0) or 0)
        if len(rows) >= total or page >= 200:
            break
        page += 1
        time.sleep(SLEEP_SEC)
    return pd.DataFrame(rows)


def save_atomic(df, path):
    tmp = path + ".tmp"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    os.replace(tmp, path)


def race_dates(history, start, end):
    d = pd.read_csv(history, usecols=["date"], dtype={"date": str})["date"].drop_duplicates()
    return sorted(x for x in d if start <= x <= end)


def main():
    ap = argparse.ArgumentParser(description="한국마사회 경주성적정보 수집 (서울)")
    ap.add_argument("--key", default=os.environ.get("KRA_API_KEY"), help="공공데이터포털 Encoding 인증키 (환경변수 KRA_API_KEY 도 가능)")
    ap.add_argument("--probe", help="이 날짜(YYYYMMDD) 하루만 받아 응답 모양을 보여주고 race_details_probe_날짜.csv 로 저장")
    ap.add_argument("--start", default="20000101", help="수집 시작일 YYYYMMDD (기본 20000101 = 전체)")
    ap.add_argument("--end", help="수집 종료일 YYYYMMDD (기본: merged.csv 의 마지막 경주일)")
    ap.add_argument("--history", default="merged.csv", help="경마 개최일을 알아낼 과거 기록 파일")
    ap.add_argument("--limit", type=int, default=2900, help="하루 최대 요청 수 (기본 2900, 개발계정 한도 3000)")
    args = ap.parse_args()

    if not args.key:
        sys.exit("인증키가 필요합니다: 환경변수 KRA_API_KEY 를 설정하거나 --key 로 넣어 주세요")
    os.makedirs(OUT_DIR, exist_ok=True)
    usage = Usage(args.limit)
    session = requests.Session()

    if args.probe:
        df = fetch_day(args.probe, args.key, usage, session, verbose=True)
        if df.empty:
            sys.exit(f"{args.probe} 경주성적 정보가 비어 있습니다. 경마가 없던 날이거나 아직 확정되지 않았을 수 있어요.")
        path = f"race_details_probe_{args.probe}.csv"
        save_atomic(df, path)
        print(f"받은 행 수: {len(df)} (원본 그대로 {path} 에 저장)")
        print("응답 항목:", list(df.columns))
        for c in df.columns:
            if c.lower() in ("rcno", "rc_no", "raceno"):
                print(f"경주별 행 수 ({c}):", df[c].value_counts().sort_index().to_dict())
        print(df.head(5).T.to_string())
        return

    if not os.path.exists(args.history):
        sys.exit(f"{args.history} 가 없습니다. 이 폴더에서 실행하거나 --history 로 경로를 알려 주세요.")
    end = args.end or pd.read_csv(args.history, usecols=["date"], dtype={"date": str})["date"].max()
    dates = race_dates(args.history, args.start, end)
    todo = [d for d in dates if not os.path.exists(os.path.join(OUT_DIR, f"rd_{d}.csv"))]
    print(f"개최일 {len(dates)}일 ({dates[0] if dates else '-'} ~ {dates[-1] if dates else '-'}) 중 받을 날 {len(todo)}일 "
          f"| 오늘 남은 요청 {usage.limit - usage.count}건")

    done = 0
    try:
        for d in todo:
            if os.path.exists(STOP_FILE):
                os.remove(STOP_FILE)
                print("STOP 신호로 멈춥니다. 다시 실행하면 이어서 받습니다.")
                break
            df = fetch_day(d, args.key, usage, session)
            save_atomic(df, os.path.join(OUT_DIR, f"rd_{d}.csv"))
            done += 1
            print(f"{d}: {len(df)}행 저장 ({done}/{len(todo)}, 오늘 요청 {usage.count}건)")
            time.sleep(SLEEP_SEC)
        else:
            print("모두 받았습니다.")
    except LimitReached:
        print(f"오늘 요청 한도({usage.limit}건)에 도달했습니다. 내일 다시 실행하면 이어서 받습니다.")
    except RuntimeError as e:
        print(f"중단: {e}\n다시 실행하면 이어서 받습니다.")
    except KeyboardInterrupt:
        print("사용자가 중단했습니다. 다시 실행하면 이어서 받습니다.")


if __name__ == "__main__":
    main()
