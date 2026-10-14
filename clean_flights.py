# -*- coding: utf-8 -*-
"""
=============================================================
  ניקוי FLIGHTS.CSV  ->  קובץ נקי מוכן ל-Power BI
  פרויקט BI מסכם - ניתוח עיכובי טיסות DOT 2015
=============================================================

הוראות הפעלה:
  1. שים את הקובץ הזה באותה תיקייה שבה נמצא flights.csv
  2. פתח שורת פקודה (CMD) בתיקייה הזאת
  3. הרץ:   pip install pandas pyarrow
  4. הרץ:   python clean_flights.py

זמן ריצה משוער: 2-5 דקות.
"""

import os
import sys

try:
    import pandas as pd
except ImportError:
    sys.exit("חסרה ספריית pandas. הרץ:  pip install pandas pyarrow")

# ------------------------------------------------------------
# הגדרות
# ------------------------------------------------------------
INPUT_FILE  = "flights.csv"
OUTPUT_FILE = "flights_clean.parquet"
CHUNK_SIZE  = 500_000          # קריאה במנות כדי לא להעמיס על הזיכרון

# עמודות שנשמרות (11 עמודות מיותרות נזרקות כבר בשלב הקריאה)
KEEP_COLS = [
    "YEAR", "MONTH", "DAY", "DAY_OF_WEEK",
    "AIRLINE", "ORIGIN_AIRPORT", "DESTINATION_AIRPORT",
    "SCHEDULED_DEPARTURE", "DEPARTURE_DELAY",
    "SCHEDULED_ARRIVAL", "ARRIVAL_DELAY",
    "DISTANCE", "DIVERTED", "CANCELLED", "CANCELLATION_REASON",
    "AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY",
    "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY",
]

DELAY_CAUSE_COLS = [
    "AIR_SYSTEM_DELAY", "SECURITY_DELAY", "AIRLINE_DELAY",
    "LATE_AIRCRAFT_DELAY", "WEATHER_DELAY",
]

DTYPES = {
    "AIRLINE": "string",
    "ORIGIN_AIRPORT": "string",
    "DESTINATION_AIRPORT": "string",
    "CANCELLATION_REASON": "string",
}

REASON_MAP = {
    "A": "Airline / Carrier",
    "B": "Weather",
    "C": "National Air System",
    "D": "Security",
}

DOW_MAP = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday",
           5: "Friday", 6: "Saturday", 7: "Sunday"}


def hhmm_to_time(series):
    """ממיר מספר בפורמט HHMM (למשל 545) לטקסט שעה HH:MM."""
    s = pd.to_numeric(series, errors="coerce")
    s = s.where(s != 2400, 0)                 # 2400 = חצות
    hh = (s // 100).astype("Int64")
    mm = (s % 100).astype("Int64")
    return hh, mm


def clean_chunk(df):
    # --- מוקש אוקטובר: קודי שדות תעופה מספריים בני 5 ספרות ---
    o = df["ORIGIN_AIRPORT"].astype("string").str.strip()
    d = df["DESTINATION_AIRPORT"].astype("string").str.strip()
    df["ORIGIN_IATA"] = o.where(o.str.len() == 3)
    df["DEST_IATA"]   = d.where(d.str.len() == 3)
    df.drop(columns=["ORIGIN_AIRPORT", "DESTINATION_AIRPORT"], inplace=True)

    # --- עמודות פירוק העיכוב: null פירושו 0 דקות תרומה ---
    for c in DELAY_CAUSE_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype("int32")

    # --- סיבת ביטול: פענוח האותיות + מילוי חסרים ---
    df["CANCELLATION_REASON"] = (
        df["CANCELLATION_REASON"].astype("string").str.strip()
          .map(REASON_MAP).fillna("Not Cancelled")
    )

    # --- עמודת תאריך אמיתית ---
    df["FLIGHT_DATE"] = pd.to_datetime(
        dict(year=df.YEAR, month=df.MONTH, day=df.DAY), errors="coerce"
    )

    # --- שעת המראה מתוכננת: שעה שלמה + טקסט, לניתוח לפי שעות היום ---
    hh, mm = hhmm_to_time(df["SCHEDULED_DEPARTURE"])
    df["DEP_HOUR"] = hh.astype("Int16")
    df["SCHEDULED_DEPARTURE"] = (
        hh.astype("string").str.zfill(2) + ":" + mm.astype("string").str.zfill(2)
    )
    hh2, mm2 = hhmm_to_time(df["SCHEDULED_ARRIVAL"])
    df["SCHEDULED_ARRIVAL"] = (
        hh2.astype("string").str.zfill(2) + ":" + mm2.astype("string").str.zfill(2)
    )

    # --- שם יום בשבוע (קריא בדשבורד) ---
    df["DAY_NAME"] = df["DAY_OF_WEEK"].map(DOW_MAP).astype("string")

    # --- דגלים מוכנים לשימוש ---
    # טיסה נחשבת "מאחרת" מ-15 דקות ומעלה (הגדרת ה-DOT הרשמית)
    df["IS_DELAYED"] = (df["ARRIVAL_DELAY"] >= 15).astype("int8")
    df["IS_ONTIME"]  = ((df["ARRIVAL_DELAY"] < 15) & df["ARRIVAL_DELAY"].notna()).astype("int8")

    # --- טיפוסים חסכוניים ---
    for c in ["DEPARTURE_DELAY", "ARRIVAL_DELAY"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int32")
    df["DISTANCE"]    = pd.to_numeric(df["DISTANCE"], errors="coerce").astype("int32")
    df["CANCELLED"]   = df["CANCELLED"].astype("int8")
    df["DIVERTED"]    = df["DIVERTED"].astype("int8")
    df["MONTH"]       = df["MONTH"].astype("int8")
    df["DAY_OF_WEEK"] = df["DAY_OF_WEEK"].astype("int8")

    df.drop(columns=["YEAR", "DAY"], inplace=True)
    return df


def main():
    if not os.path.exists(INPUT_FILE):
        sys.exit(f"לא נמצא הקובץ '{INPUT_FILE}'. שים את הסקריפט באותה תיקייה.")

    print("קורא את הקובץ ומנקה... (זה ייקח כמה דקות)\n")

    parts, total = [], 0
    reader = pd.read_csv(INPUT_FILE, usecols=KEEP_COLS, dtype=DTYPES,
                         chunksize=CHUNK_SIZE, low_memory=False)
    for i, chunk in enumerate(reader, 1):
        total += len(chunk)
        parts.append(clean_chunk(chunk))
        print(f"  מנה {i:>2} | {total:>9,} שורות עובדו")

    df = pd.concat(parts, ignore_index=True)
    del parts

    # בדיקת כפילויות מלאות
    before = len(df)
    df.drop_duplicates(inplace=True)
    dropped = before - len(df)

    # סדר עמודות נוח
    order = ["FLIGHT_DATE", "MONTH", "DAY_OF_WEEK", "DAY_NAME", "AIRLINE",
             "ORIGIN_IATA", "DEST_IATA", "SCHEDULED_DEPARTURE", "DEP_HOUR",
             "SCHEDULED_ARRIVAL", "DEPARTURE_DELAY", "ARRIVAL_DELAY",
             "IS_DELAYED", "IS_ONTIME", "DISTANCE", "CANCELLED", "DIVERTED",
             "CANCELLATION_REASON"] + DELAY_CAUSE_COLS
    df = df[order]

    try:
        df.to_parquet(OUTPUT_FILE, index=False, compression="snappy")
        out = OUTPUT_FILE
    except Exception:
        out = "flights_clean.csv"
        print("\n(pyarrow לא מותקן - שומר כ-CSV במקום)")
        df.to_csv(out, index=False, encoding="utf-8-sig")

    size_mb = os.path.getsize(out) / 1024 / 1024
    oct_bad = df["ORIGIN_IATA"].isna().sum()

    print("\n" + "=" * 52)
    print("  סיכום ניקוי")
    print("=" * 52)
    print(f"  סה\"כ שורות              : {len(df):>10,}")
    print(f"  כפילויות שנמחקו         : {dropped:>10,}")
    print(f"  טיסות שבוטלו            : {int(df.CANCELLED.sum()):>10,}")
    print(f"  טיסות שהוסטו            : {int(df.DIVERTED.sum()):>10,}")
    print(f"  טיסות מאחרות (15 דק'+)  : {int(df.IS_DELAYED.sum()):>10,}")
    print(f"  ללא קוד שדה (אוקטובר)   : {oct_bad:>10,}")
    print(f"  עמודות                  : {len(df.columns):>10}")
    print("-" * 52)
    print(f"  נוצר הקובץ: {out}  ({size_mb:,.1f} MB)")
    print("=" * 52)


if __name__ == "__main__":
    main()
