import csv
import os


INPUT_FILE = "rs3_candidates_500eok.csv"
OUTPUT_FILE = "rs3_candidates_minute_period.csv"

# 실제 키움 1분봉 조회 테스트에서 확인된 최과거 날짜
MIN_DATE = "20250801"


print("=" * 70)
print("Reverse SPES RS3 - 1분봉 검증 가능기간 필터")
print("기준일 : 2025-08-01 이후")
print("=" * 70)


if not os.path.exists(INPUT_FILE):
    print()
    print("❌ 파일을 찾을 수 없습니다.")
    print("필요 파일 :", INPUT_FILE)
    print()
    input("Enter를 누르면 종료합니다...")
    raise SystemExit


total = 0
passed = []


with open(
    INPUT_FILE,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)

    for row in reader:

        total += 1

        date = str(
            row.get("date", "")
        ).strip()

        if not date:
            continue

        if date < MIN_DATE:
            continue

        passed.append(row)


fields = [
    "stock_code",
    "stock_name",
    "market",
    "date",
    "open",
    "high",
    "rise_pct",
    "traded_value_raw",
    "traded_value_eok"
]


with open(
    OUTPUT_FILE,
    "w",
    newline="",
    encoding="utf-8-sig"
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=fields
    )

    writer.writeheader()
    writer.writerows(passed)


print()
print("거래대금 500억 이상 전체 :", f"{total:,}건")
print(
    "2025-08-01 이후 후보     :",
    f"{len(passed):,}건"
)

if total:

    rate = len(passed) / total * 100

    print(
        "분봉 검증 가능 비율      :",
        f"{rate:.2f}%"
    )


print()
print("=" * 70)
print("최근 후보 예시 20건")
print("=" * 70)


# 날짜 최신순으로 표시
display_rows = sorted(
    passed,
    key=lambda x: x.get("date", ""),
    reverse=True
)


for row in display_rows[:20]:

    print(
        row.get("date"),
        "/",
        row.get("stock_code"),
        row.get("stock_name"),
        "/ 상승률:",
        row.get("rise_pct"),
        "%",
        "/ 거래대금:",
        row.get("traded_value_eok"),
        "억원"
    )


print()
print("저장 파일 :", OUTPUT_FILE)
print()
print("✅ 1분봉 검증 대상 기간 필터 완료")

print()
input("Enter를 누르면 종료합니다...")
