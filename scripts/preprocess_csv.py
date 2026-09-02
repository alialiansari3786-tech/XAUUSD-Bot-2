"""
CSV Preprocessor
Adds volume column if missing and standardizes format
"""

import pandas as pd
from pathlib import Path

# CSV directory
csv_dir = Path("C:/Aman Ansari/New XAUUSD/data/historical")

# Process each CSV file
files = list(csv_dir.glob("XAUUSD_*.csv"))

print(f"Found {len(files)} CSV files to process")

for csv_file in files:
    print(f"\nProcessing: {csv_file.name}")

    try:
        # Read CSV
        df = pd.read_csv(csv_file)

        print(f"  Original columns: {list(df.columns)}")
        print(f"  Rows: {len(df)}")

        # Check if volume exists
        if 'volume' not in df.columns and 'Volume' not in df.columns:
            print("  Adding volume column...")
            # Add synthetic volume based on price range
            df['volume'] = ((df['high'] - df['low']) * 1000).astype(int)

        # Standardize column names
        df.columns = df.columns.str.lower()

        # Rename time column to datetime
        if 'time' in df.columns:
            df = df.rename(columns={'time': 'datetime'})

        # Ensure correct order
        df = df[['datetime', 'open', 'high', 'low', 'close', 'volume']]

        # Save back
        df.to_csv(csv_file, index=False)

        print(f"  ✓ Processed successfully")
        print(f"  Final columns: {list(df.columns)}")

    except Exception as e:
        print(f"  ✗ Error: {e}")

print("\n" + "="*50)
print("CSV preprocessing complete!")
print("="*50)
