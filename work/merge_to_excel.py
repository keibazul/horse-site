import os
import re
import glob
import json

import pandas as pd

# =====================================================
# 설정
# =====================================================
DATA_DIR = "race_data"            # 수집기가 만든 폴더 (data1.json, index.csv 가 들어 있는 곳)
OUT_JSON = "merged.json"
OUT_CSV = "merged.csv"
OUT_EXCEL = "merged.xlsx"

SAVE_JSON = True
SAVE_CSV = True                   # 행이 너무 많아 엑셀이 무거울 때를 대비한 CSV (엑셀에서 한글 안 깨지게 utf-8-sig)
SAVE_EXCEL = True

EXCEL_MAX_ROWS = 1_048_575        # 엑셀 시트 하나에 들어가는 최대 데이터 행 수 (제목 행 제외)


# =====================================================
# 1. data*.json 을 숫자 순서대로 읽기
# =====================================================
def file_number(path):
    return int(re.search(r"data(\d+)\.json$", path).group(1))


files = sorted(
    glob.glob(os.path.join(DATA_DIR, "**", "data*.json"), recursive=True),
    key=file_number,
)
if not files:
    raise SystemExit(f"'{DATA_DIR}' 폴더에서 data*.json 파일을 찾지 못했습니다.")
print(f"JSON 파일 {len(files)}개를 읽는 중...")

all_items = []
skipped = []

for path in files:
    no = file_number(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        items = data["response"]["body"]["items"]["item"]
    except (KeyError, TypeError, ValueError):
        skipped.append(os.path.basename(path))  # 구조가 다르거나 비어 있는 파일
        continue

    if isinstance(items, dict):  # 결과가 1행이면 리스트가 아니라 dict로 옴
        items = [items]

    for it in items:
        it["file_no"] = no       # 어느 파일에서 왔는지 표시
    all_items.extend(items)

print(f"병합된 행 수: {len(all_items):,}")
if skipped:
    print(f"읽지 못한 파일 {len(skipped)}개: {', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}")
if not all_items:
    raise SystemExit("병합할 데이터가 없습니다. data1.json 의 구조를 확인해 주세요.")


# =====================================================
# 2. 표로 만들고 index.csv(날짜, 경주번호) 붙이기
# =====================================================
df = pd.json_normalize(all_items)

index_path = os.path.join(DATA_DIR, "index.csv")
if os.path.exists(index_path):
    index_df = pd.read_csv(index_path, dtype={"date": str})
    df = df.merge(index_df, on="file_no", how="left")
    front = ["date", "race_no", "file_no"]
else:
    front = ["file_no"]

df = df[front + [c for c in df.columns if c not in front]]  # 앞쪽 열 순서 정리


# =====================================================
# 3. 저장
# =====================================================
if SAVE_JSON:
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False)
    print(f"저장 완료: {OUT_JSON}")

if SAVE_CSV:
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")
    print(f"저장 완료: {OUT_CSV}")

if SAVE_EXCEL:
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        raise SystemExit("엑셀 저장에는 openpyxl이 필요합니다.  pip install openpyxl")

    if len(df) <= EXCEL_MAX_ROWS:
        df.to_excel(OUT_EXCEL, index=False)
    elif "date" in df.columns:
        # 한 시트에 다 안 들어가면 연도별 시트로 나눠서 저장
        print("행 수가 엑셀 한도를 넘어서 연도별 시트로 나눠 저장합니다.")
        with pd.ExcelWriter(OUT_EXCEL) as writer:
            for year, part in df.groupby(df["date"].str[:4]):
                part.to_excel(writer, sheet_name=str(year), index=False)
    else:
        print("행 수가 엑셀 한도를 넘었습니다. CSV 파일을 사용해 주세요.")
        SAVE_EXCEL = False

    if SAVE_EXCEL:
        print(f"저장 완료: {OUT_EXCEL}")

print("끝!")
