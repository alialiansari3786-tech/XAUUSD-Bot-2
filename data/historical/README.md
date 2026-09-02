# Historical CSV Data Format

Place your XAUUSD historical CSV files in this directory for backtesting.

## File Naming Convention

Files should be named: `XAUUSD_{timeframe}.csv`

Examples:
- `XAUUSD_M1.csv` - 1-minute data
- `XAUUSD_M5.csv` - 5-minute data
- `XAUUSD_M15.csv` - 15-minute data
- `XAUUSD_H1.csv` - 1-hour data
- `XAUUSD_D1.csv` - Daily data

## CSV Format

### Required Columns

Your CSV must contain these columns (case-insensitive):

1. **datetime** (or date, time, timestamp) - Date/time in ISO format or Unix timestamp
2. **open** - Opening price
3. **high** - High price
4. **low** - Low price
5. **close** - Closing price
6. **volume** - Trading volume

### Example CSV Structure

```csv
datetime,open,high,low,close,volume
2026-08-01 00:00:00,2450.25,2452.50,2449.00,2451.75,15234
2026-08-01 00:15:00,2451.75,2453.00,2450.50,2452.25,12456
2026-08-01 00:30:00,2452.25,2454.75,2451.00,2454.00,18923
...
```

### Datetime Formats Supported

- ISO 8601: `2026-08-01 00:00:00` or `2026-08-01T00:00:00`
- Unix timestamp: `1722470400`
- Date only (for daily data): `2026-08-01`

## Data Quality

Ensure your CSV data:
- Has no missing values in OHLCV columns
- Is sorted chronologically (oldest to newest)
- Has valid OHLC relationships (High >= Low, Close between High and Low)
- Has no duplicate timestamps
- Has consistent time intervals

## Usage

To run the bot with CSV data:

```python
from src.core.data_fetcher import DataFetcher

# Enable CSV mode
fetcher = DataFetcher(use_csv=True)

# Fetch data
data = fetcher.fetch_data('M15')
```

Or run backtesting script:

```bash
python scripts/backtest.py --csv-data
```

## Notes

- CSV data takes priority over API data when `use_csv=True`
- Perfect for backtesting strategies without API rate limits
- Useful for testing bot behavior with known historical patterns
- Can include data from any source (broker exports, other APIs, etc.)
