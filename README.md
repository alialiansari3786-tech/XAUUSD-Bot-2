# XAUUSD Trading Bot

Automated Gold (XAUUSD) trading analysis bot implementing three distinct trading methodologies with Telegram dashboard integration.

## Features

- **Three Trading Methods**:
  1. **Combined Method**: Multi-timeframe analysis (Weekly, Daily, 4H, 1H, 15m, 5m/3m) with STL/STH structure tracking
  2. **Monthly-Daily-Hourly-5m**: Percentage-based structure analysis (25% Daily, 37.5% H1/M5 pullbacks)
  3. **Liquidity + SAR Strategy**: Liquidity-driven entries with Support/Resistance confirmation system

- **Advanced Features**:
  - Volumetric Order Block detection with internal buy/sell metrics
  - MSS/CHoCH/CHoCH+ structure identification
  - FVG/VI/OG gap detection
  - EQH/EQL detection using ATR-based tolerance
  - Fresh/Unfresh S/R level tracking
  - W/M pattern classification (Strong vs Weak)
  - Multi-timeframe confluence scoring
  - Premium/Discount zone analysis

- **Data Source**: yfinance (XAUUSD=X spot price, 15-minute updates)

- **Telegram Integration**:
  - Real-time trade notifications
  - Chart images with marked levels
  - Daily summaries
  - Weekly recaps
  - Full dashboard delivery

- **Claude Vision API**: Trade screenshot analysis for pattern learning

## Project Structure

```
New XAUUSD/
├── src/
│   ├── core/
│   │   ├── __init__.py
│   │   ├── data_fetcher.py          # yfinance data fetching
│   │   ├── structure_detector.py     # MSS/CHoCH/BOS detection
│   │   ├── order_block_detector.py   # OB detection (volumetric + standard)
│   │   ├── fvg_detector.py           # Fair Value Gap detection
│   │   ├── liquidity_detector.py     # Liquidity level detection
│   │   ├── sar_detector.py           # Support/Resistance system
│   │   └── pattern_detector.py       # W/M pattern recognition
│   ├── methods/
│   │   ├── __init__.py
│   │   ├── combined_method.py        # Method 1: Combined Method
│   │   ├── percentage_method.py      # Method 2: Monthly-Daily-Hourly-5m
│   │   └── liquidity_sar_method.py   # Method 3: Liquidity + SAR
│   ├── indicators/
│   │   ├── __init__.py
│   │   ├── guardeer.py               # Guardeer indicator logic
│   │   └── smart_money.py            # Smart Money Concepts logic
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── telegram_bot.py           # Telegram notification system
│   │   ├── claude_vision.py          # Screenshot analysis
│   │   └── chart_generator.py        # Chart image generation
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── timeframe_utils.py        # Timeframe conversion utilities
│   │   ├── confluence_scorer.py      # Confluence calculation
│   │   └── logger.py                 # Logging setup
│   └── main.py                        # Main scheduler and orchestrator
├── config/
│   ├── __init__.py
│   ├── settings.py                    # Configuration management
│   └── .env.template                  # Environment variables template
├── tests/
│   ├── __init__.py
│   ├── test_structure_detector.py
│   ├── test_order_block_detector.py
│   └── test_methods.py
├── data/                              # Data storage (gitignored)
├── logs/                              # Log files (gitignored)
├── charts/                            # Generated charts (gitignored)
├── requirements.txt                   # Python dependencies
├── .gitignore
├── README.md
└── setup.py
```

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd "C:\Aman Ansari\New XAUUSD"
```

2. Create virtual environment:
```bash
python -m venv venv
venv\Scripts\activate  # Windows
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Configure environment variables:
```bash
cp config/.env.template config/.env
# Edit config/.env with your Telegram token and chat ID
```

## Configuration

Edit `config/.env`:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
TELEGRAM_CHAT_ID=your_telegram_chat_id_here
CLAUDE_API_KEY=your_claude_api_key_here
SCAN_INTERVAL_MINUTES=15
LOG_LEVEL=INFO
```

## Usage

Run the bot:
```bash
python src/main.py
```

Run specific method:
```bash
python src/main.py --method combined
python src/main.py --method percentage
python src/main.py --method liquidity_sar
```

Run in test mode (no Telegram notifications):
```bash
python src/main.py --test
```

## Trading Methods

### Method 1: Combined Method
Multi-timeframe structure analysis tracking STL/STH with IDM (Inducement) points. Identifies trading ranges across Weekly, Daily, 4H, 1H, 15m timeframes and marks Order Blocks within valid ranges. Entry on 15m/5m with confluence scoring.

**Key Features**:
- STL/STH tracking with confirmation points
- IDM identification
- Trading Range validation
- Multi-TF OB alignment (Daily+4H, Daily+1H, 4H+1H, Daily+4H+1H)
- HTF pullback scenarios

### Method 2: Monthly-Daily-Hourly-5m
Percentage-based structure analysis using 25% Daily and 37.5% H1/M5 pullback requirements with Fibonacci zones (0, 0.25, 0.375, 0.5, 1).

**Key Features**:
- Simple MSS + ICT MSS options
- Monthly TF for target projection
- Percentage pullback validation
- Premium/Discount zone entries
- Trade lifecycle phases (Expansion → Pullback → Entry → Continuation)

### Method 3: Liquidity + SAR Strategy
Liquidity-driven entries with comprehensive Support/Resistance confirmation system. Implements friend's SAR strategy with Fresh/Unfresh level tracking and W/M pattern classification.

**Key Features**:
- Liquidity sweep detection (Weekly/Daily HL, Swing HL, EQH/EQL, Old HL, DOL)
- Fresh vs Unfresh S/R level tracking
- Strong W vs Weak W pattern classification
- Multi-layer confirmation (8-step validation)
- Trade zone identification (OB+FVG+S/R confluence)
- Multi-entry logic on fresh levels
- Confluence scoring (minimum 7 points required)

## Technical Indicators

### Guardeer Indicator
- Volumetric Order Blocks with buy/sell metrics
- MSS/CHoCH/CHoCH+ detection
- EQH/EQL with ATR(200) * 0.1 tolerance
- FVG/VI/OG detection
- Impulse indicator
- Accumulation/Distribution zones

### Smart Money Concepts
- Standard Order Blocks
- FVG with auto-threshold (bar delta percentage)
- Premium/Discount zones (95-100% / 47.5-52.5% / 0-5%)
- Structure detection with historical vs present mode
- Strong/Weak High/Low labels

## Telegram Dashboard

Notifications include:
- **Trade Alerts**: Entry signals with full setup details (entry, SL, TP, confluence score)
- **Chart Images**: Annotated charts showing all levels, zones, and structure
- **Daily Summary**: End-of-day recap with all signals, win rate, key levels for next day
- **Weekly Recap**: Sunday summary with weekly performance, major structure shifts, upcoming key levels

## Data Sources (Dual Redundancy)

### Primary: yfinance
- Free, no API key required
- 15-minute delayed data
- Perfect for 15-minute scan frequency
- XAUUSD=X ticker
- **Status:** ✅ Production ready

### Fallback: Twelve Data
- Free tier: 800 calls/day, 8 calls/minute
- Explicitly supports XAUUSD
- India-accessible
- Automatic failover if yfinance fails
- **Setup:** Add `TWELVE_DATA_API_KEY` to `.env` (get free key at [twelvedata.com](https://twelvedata.com))
- **Status:** ✅ Production ready

### Historical Testing (One-Time Use)
- CSV files provided for initial backtesting
- Located in `data/historical/` directory
- Used once to validate bot logic
- **Not used in production** - Live data only

## Data Limitations

- **yfinance**: 15-minute delay (acceptable for analysis)
- **Twelve Data Free**: 800 calls/day limit
- **Historical Data**: yfinance M5/M3 limited to 7 days (use CSV for backtesting)

## Backtesting

Test strategies against historical data:

```bash
# Using CSV data
python scripts/backtest.py --csv-data

# Using live API
python scripts/backtest.py --live-api

# Test specific methods
python scripts/backtest.py --csv-data --methods combined percentage

# Test all methods (default)
python scripts/backtest.py --csv-data --methods all
```

### Preparing CSV Data

1. Place CSV files in `data/historical/`
2. Name format: `XAUUSD_M15.csv`, `XAUUSD_H1.csv`, etc.
3. Required columns: datetime, open, high, low, close, volume
4. See `data/historical/README.md` for details

## Development

Run tests:
```bash
pytest tests/
```

Code formatting:
```bash
black src/
```

Linting:
```bash
flake8 src/
```

## License

Private project - All rights reserved

## Support

For issues or questions, contact the development team.

## Version

Current Version: 0.1.0 (Initial Development)
