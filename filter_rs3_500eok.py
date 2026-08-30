import csv
import os


INPUT_FILE = "rs3_market_candidates.csv"
OUTPUT_FILE = "rs3_candidates_500eok.csv"

# 키움 일봉 거래대금 단위: 백만원
# 500억원 = 50,000백만원
MIN_TRADED_VALUE = 50000


def to_number(value):
    try:
        return int(
            str(value)
            .replace(",", "")
            .strip()
        )
    except:
        return 0


print("=" * 70)
print("Reverse SPES RS3 - 거래대금 500억원 필터")
print("=" * 70)


if not os.path.exists(INPUT_FILE):
    print()
    print("❌ 파일을 찾을 수 없습니다.")
    print("필요 파일 :", INPUT_FILE)
    print()
    input("Enter를 누르면 종료합니다...")
    raise SystemExit


passed = []
total = 0


with open(
    INPUT_FILE,
    "r",
    encoding="utf-8-sig"
) as f:

    reader = csv.DictReader(f)

    for row in reader:

        total += 1

        traded_value = to_number(
            row.get("traded_value_raw")
        )

        # RS3 원문 조건
        # 거래대금 최소 500억원 이상
        if traded_value < MIN_TRADED_VALUE:
            continue

        row["traded_value_eok"] = round(
            traded_value / 100,
            2
        )

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
print("기존 +20% 후보 :", f"{total:,}건")
print(
    "거래대금 500억 이상 :",
    f"{len(passed):,}건"
)

if total > 0:

    rate = (
        len(passed)
        / total
        * 100
    )

    print(
        "통과 비율 :",
        f"{rate:.2f}%"
    )


print()
print("=" * 70)
print("500억원 이상 후보 예시 20건")
print("=" * 70)


for row in passed[:20]:

    print(
        row["date"],
        "/",
        row["stock_code"],
        row["stock_name"],
        "/ 상승률:",
        row["rise_pct"],
        "%",
        "/ 거래대금:",
        row["traded_value_eok"],
        "억원"
    )


print()
print("저장 파일 :", OUTPUT_FILE)

print()
print("✅ RS3 거래대금 500억원 필터 완료")

print()
input("Enter를 누르면 종료합니다...")
