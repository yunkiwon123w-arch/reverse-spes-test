# -*- coding: utf-8 -*-
"""
RS20 SOURCE LABEL STUDY v1
==========================

Purpose
- Freeze the lecture's stock-classification examples as SOURCE LABELS.
- Cross-match those source-labeled stocks against the already collected
  RS20 candidate-day investor-flow dataset.
- Measure whether investor-flow alone can distinguish:
    세력주 / 수급주 / 수급세력주
- NO Kiwoom API.
- NO orders.
- NO invented thresholds.

Important interpretation
- Lecture labels are stock examples shown in Chapter 02.
- Candidate-day investor data are later dates, so this is an
  OUT-OF-SAMPLE CONSISTENCY STUDY, not proof of the lecture's exact
  classification formula.
"""

import csv
from collections import defaultdict
from pathlib import Path
from statistics import median

INPUT_FILE = "rs20_investor_flow_candidates_v1.csv"

OUT_SOURCE_LABELS = "rs20_source_stock_labels_v1.csv"
OUT_MATCHED = "rs20_source_label_candidate_matches_v1.csv"
OUT_SUMMARY = "rs20_source_label_study_summary_v1.txt"

SOURCE_LABELS = [
    # 세력주: lecture 1, pp.9-14
    (9,  "세력주", "오리엔트정공"),
    (10, "세력주", "범양건영"),
    (11, "세력주", "화성밸브"),
    (12, "세력주", "대동기어"),
    (13, "세력주", "이랜시스"),
    (14, "세력주", "씨씨에스"),

    # 수급주: lecture 1, pp.15-21
    (15, "수급주", "두산에너빌리티"),
    (16, "수급주", "카카오"),
    (17, "수급주", "HD현대중공업"),
    (18, "수급주", "더존비즈온"),
    (19, "수급주", "JYP Ent."),
    (20, "수급주", "크래프톤"),
    (21, "수급주", "HD현대일렉트릭"),

    # 수급세력주: lecture 1, pp.22-27
    (22, "수급세력주", "한국가스공사"),
    (23, "수급세력주", "루닛"),
    (24, "수급세력주", "한화오션"),
    (25, "수급세력주", "유한양행"),
    (26, "수급세력주", "레인보우로보틱스"),
    (27, "수급세력주", "알테오젠"),
]

NUMERIC_FIELDS = [
    "ind_invsr", "frgnr_invsr", "orgn", "fnnc_invt",
    "insrnc", "invtrt", "etc_fnnc", "bank",
    "penfnd_etc", "samo_fund", "natn", "etc_corp", "natfor",
    "eod_traded_value_eok", "eod_m_value_eok", "eod_m_ratio_pct",
]

FOCUS_FIELDS = [
    "ind_invsr", "frgnr_invsr", "orgn",
    "fnnc_invt", "invtrt", "penfnd_etc", "samo_fund", "etc_corp",
]


def sf(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None


def read_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path, fields, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def pct(n, d):
    return (n / d * 100.0) if d else 0.0


def fmt_num(x):
    return "" if x is None else f"{x:.3f}"


def main():
    base = Path(__file__).resolve().parent
    inp = base / INPUT_FILE
    if not inp.exists():
        raise SystemExit(f"REQUIRED FILE NOT FOUND: {INPUT_FILE}")

    rows = read_csv(inp)

    label_rows = [
        {
            "lecture_page": page,
            "source_label": label,
            "stock_name": name,
            "source_status": "SOURCE_CONFIRMED_EXAMPLE",
            "interpretation_note":
                "Lecture stock-classification example; no numeric classification threshold implied."
        }
        for page, label, name in SOURCE_LABELS
    ]
    write_csv(
        base / OUT_SOURCE_LABELS,
        ["lecture_page", "source_label", "stock_name", "source_status", "interpretation_note"],
        label_rows
    )

    # A small normalization set only for naming variants, not strategy logic.
    aliases = {
        "JYP Ent": "JYP Ent.",
        "JYP Ent.": "JYP Ent.",
        "에이치디현대중공업": "HD현대중공업",
        "에이치디현대일렉트릭": "HD현대일렉트릭",
    }

    source_by_name = {}
    for page, label, name in SOURCE_LABELS:
        source_by_name[name] = (page, label, name)

    matched = []
    for r in rows:
        raw_name = str(r.get("stock_name", "")).strip()
        norm_name = aliases.get(raw_name, raw_name)

        if norm_name not in source_by_name:
            continue

        page, label, canonical = source_by_name[norm_name]
        out = dict(r)
        out["lecture_page"] = page
        out["source_label"] = label
        out["source_stock_name"] = canonical
        out["study_type"] = "OUT_OF_SAMPLE_CONSISTENCY"

        for f in NUMERIC_FIELDS:
            out[f] = sf(r.get(f))

        # sign features only; no threshold invention.
        out["individual_net_buy_sign"] = (
            "BUY" if out["ind_invsr"] is not None and out["ind_invsr"] > 0
            else "SELL" if out["ind_invsr"] is not None and out["ind_invsr"] < 0
            else "ZERO"
        )
        out["foreign_net_buy_sign"] = (
            "BUY" if out["frgnr_invsr"] is not None and out["frgnr_invsr"] > 0
            else "SELL" if out["frgnr_invsr"] is not None and out["frgnr_invsr"] < 0
            else "ZERO"
        )
        out["institution_net_buy_sign"] = (
            "BUY" if out["orgn"] is not None and out["orgn"] > 0
            else "SELL" if out["orgn"] is not None and out["orgn"] < 0
            else "ZERO"
        )
        out["foreign_and_institution_buy"] = (
            "Y" if (out["frgnr_invsr"] or 0) > 0 and (out["orgn"] or 0) > 0 else "N"
        )
        out["foreign_institution_buy_individual_sell"] = (
            "Y"
            if (out["frgnr_invsr"] or 0) > 0
            and (out["orgn"] or 0) > 0
            and (out["ind_invsr"] or 0) < 0
            else "N"
        )
        matched.append(out)

    base_fields = list(rows[0].keys()) if rows else []
    extra_fields = [
        "lecture_page", "source_label", "source_stock_name", "study_type",
        "individual_net_buy_sign", "foreign_net_buy_sign",
        "institution_net_buy_sign", "foreign_and_institution_buy",
        "foreign_institution_buy_individual_sell",
    ]
    write_csv(base / OUT_MATCHED, base_fields + extra_fields, matched)

    grouped = defaultdict(list)
    for r in matched:
        grouped[r["source_label"]].append(r)

    lines = []
    lines.append("RS20 SOURCE LABEL STUDY v1")
    lines.append("=" * 72)
    lines.append(f"source_labeled_stocks_total: {len(SOURCE_LABELS)}")
    lines.append(f"candidate_rows_total: {len(rows)}")
    lines.append(f"matched_candidate_rows: {len(matched)}")
    lines.append(f"matched_unique_source_stocks: {len(set(r['source_stock_name'] for r in matched))}")
    lines.append("")
    lines.append("SOURCE LABEL COUNTS")
    for label in ["세력주", "수급주", "수급세력주"]:
        src_count = sum(1 for _, lab, _ in SOURCE_LABELS if lab == label)
        mg = grouped.get(label, [])
        unique = len(set(r["source_stock_name"] for r in mg))
        lines.append(
            f"- {label}: source examples {src_count}, "
            f"matched rows {len(mg)}, matched unique stocks {unique}"
        )

    lines.append("")
    lines.append("OUT-OF-SAMPLE INVESTOR-FLOW CONSISTENCY")
    for label in ["세력주", "수급주", "수급세력주"]:
        g = grouped.get(label, [])
        lines.append("")
        lines.append(f"[{label}]")
        lines.append(f"rows={len(g)}, unique_stocks={len(set(r['source_stock_name'] for r in g))}")
        if not g:
            lines.append("No matched candidate rows.")
            continue

        for f in FOCUS_FIELDS:
            vals = [r[f] for r in g if r.get(f) is not None]
            pos = sum(1 for v in vals if v > 0)
            med = median(vals) if vals else None
            lines.append(
                f"{f}: positive={pos}/{len(vals)} ({pct(pos,len(vals)):.1f}%), "
                f"median={fmt_num(med)}"
            )

        fi = sum(1 for r in g if r["foreign_and_institution_buy"] == "Y")
        fis = sum(1 for r in g if r["foreign_institution_buy_individual_sell"] == "Y")
        lines.append(
            f"foreign+institution both BUY: {fi}/{len(g)} ({pct(fi,len(g)):.1f}%)"
        )
        lines.append(
            f"foreign+institution BUY + individual SELL: "
            f"{fis}/{len(g)} ({pct(fis,len(g)):.1f}%)"
        )

    lines.append("")
    lines.append("INTERPRETATION")
    lines.append("1. SOURCE_CONFIRMED:")
    lines.append("   Lecture 1 pp.9-27 explicitly provides the three example groups.")
    lines.append("2. SOURCE_SUPPORTED_INFERENCE:")
    lines.append("   수급주 and 수급세력주 matched rows can be checked for later-date")
    lines.append("   consistency with foreign/institution participation.")
    lines.append("3. UNRESOLVED:")
    lines.append("   The lecture does not provide a numeric threshold that mechanically")
    lines.append("   separates 수급주 from 수급세력주.")
    lines.append("4. IMPORTANT SAMPLE LIMIT:")
    lines.append("   Only source-example stocks that also appear in the 1,174 later")
    lines.append("   RS20 candidate rows are included. This is not the original lecture-date")
    lines.append("   investor-flow dataset.")
    lines.append("5. AUTOMATION DECISION:")
    lines.append("   Do NOT create a source-version classifier from these later-date signs")
    lines.append("   alone. Preserve classification as SOURCE_UNRESOLVED unless additional")
    lines.append("   source-backed mechanics are found.")
    lines.append("")
    lines.append("NO Kiwoom API. NO orders. NO invented thresholds.")

    (base / OUT_SUMMARY).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("=" * 72)
    print("RS20 SOURCE LABEL STUDY v1 COMPLETE")
    print(f"SOURCE LABEL STOCKS       : {len(SOURCE_LABELS)}")
    print(f"MATCHED CANDIDATE ROWS    : {len(matched)}")
    print(f"MATCHED UNIQUE STOCKS     : {len(set(r['source_stock_name'] for r in matched))}")
    for label in ["세력주", "수급주", "수급세력주"]:
        g = grouped.get(label, [])
        print(
            f"{label:<8} : {len(g):>3} rows / "
            f"{len(set(r['source_stock_name'] for r in g)):>2} stocks"
        )
    print(f"SOURCE LABEL FILE         : {OUT_SOURCE_LABELS}")
    print(f"MATCHED STUDY FILE        : {OUT_MATCHED}")
    print(f"SUMMARY                   : {OUT_SUMMARY}")
    print("=" * 72)


if __name__ == "__main__":
    main()
