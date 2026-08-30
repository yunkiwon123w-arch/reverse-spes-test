import csv
import os


FILE_NAME = "rs3_market_candidates.csv"


print("=" * 70)
print("RS3 후보 CSV - 거래대금 값 확인")
print("=" * 70)


if not os.path.exists(FILE_NAME):
    print()
    print("❌ 파일을 찾을 수 없습니다.")
    print("필요 파일 :", FILE_NAME)
    print()
    input("Enter를 누르면 종료합니다...")
    raise SystemExit


rows = []

with open(
    FILE_NAME,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)

    for row in reader:
        rows.append(row)


print()
print("전체 후보 수 :", len(rows))
print()

print("=" * 70)
print("앞쪽 후보 20건")
print("=" * 70)

for row in rows[:20]:

    print(
        row.get("date"),
        "/",
        row.get("stock_code"),
        row.get("stock_name"),
        "/ 시가:",
        row.get("open"),
        "/ 고가:",
        row.get("high"),
        "/ 상승률:",
        row.get("rise_pct"),
        "%",
        "/ 거래대금 원본:",
        row.get("traded_value_raw")
    )


print()
print("=" * 70)
print("거래대금이 큰 후보 20건")
print("=" * 70)


def to_number(value):
    try:
        return int(
            str(value)
            .replace(",", "")
            .strip()
        )
    except:
        return 0


sorted_rows = sorted(
    rows,
    key=lambda x: to_number(
        x.get("traded_value_raw")
    ),
    reverse=True
)


for row in sorted_rows[:20]:

    print(
        row.get("date"),
        "/",
        row.get("stock_code"),
        row.get("stock_name"),
        "/ 거래대금 원본:",
        row.get("traded_value_raw")
    )


print()
print("=" * 70)
print("확인 완료")
print("=" * 70)

print()
input("Enter를 누르면 종료합니다...")
