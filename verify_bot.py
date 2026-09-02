"""
Verification Script for XAUUSD Trading Bot
Checks all components, imports, and configurations
"""

import sys
import os
from pathlib import Path

# Color codes for terminal output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text:^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")


def print_success(text):
    print(f"{GREEN}✓{RESET} {text}")


def print_error(text):
    print(f"{RED}✗{RESET} {text}")


def print_warning(text):
    print(f"{YELLOW}⚠{RESET} {text}")


def check_file_structure():
    """Check if all required files exist"""
    print_header("File Structure Check")

    required_files = {
        'Core Modules': [
            'src/core/data_fetcher.py',
            'src/core/structure_detector.py',
            'src/core/order_block_detector.py',
            'src/core/fvg_detector.py',
            'src/core/liquidity_detector.py',
            'src/core/sar_detector.py',
            'src/core/pattern_detector.py',
        ],
        'Trading Methods': [
            'src/methods/combined_method.py',
            'src/methods/percentage_method.py',
            'src/methods/liquidity_sar_method.py',
        ],
        'Indicators': [
            'src/indicators/guardeer.py',
            'src/indicators/smart_money.py',
        ],
        'Integrations': [
            'src/integrations/telegram_bot.py',
            'src/integrations/chart_generator.py',
            'src/integrations/claude_vision.py',
        ],
        'Utilities': [
            'src/utils/logger.py',
            'src/utils/timeframe_utils.py',
            'src/utils/confluence_scorer.py',
        ],
        'Scripts': [
            'scripts/backtest.py',
            'scripts/preprocess_csv.py',
            'scripts/validate_csv.py',
        ],
        'Configuration': [
            'config/settings.py',
            'config/.env.template',
        ],
        'Main': [
            'src/main.py',
        ]
    }

    all_passed = True
    for category, files in required_files.items():
        print(f"\n{category}:")
        for file in files:
            if Path(file).exists():
                print_success(f"{file}")
            else:
                print_error(f"{file} - MISSING")
                all_passed = False

    return all_passed


def check_python_imports():
    """Check if all core modules can be imported"""
    print_header("Python Import Check")

    imports_to_check = [
        ('pandas', 'Data manipulation'),
        ('numpy', 'Numerical computing'),
        ('yfinance', 'Market data (primary)'),
        ('twelvedata', 'Market data (fallback)'),
        ('ta', 'Technical analysis'),
        ('matplotlib', 'Charting'),
        ('mplfinance', 'Financial charts'),
        ('schedule', 'Task scheduling'),
        ('anthropic', 'Claude API (optional)'),
    ]

    missing_packages = []
    for package, description in imports_to_check:
        try:
            __import__(package)
            print_success(f"{package:20s} - {description}")
        except ImportError:
            if package == 'anthropic':
                print_warning(f"{package:20s} - {description} (Optional - install if using Claude Vision)")
            else:
                print_error(f"{package:20s} - {description} - NOT INSTALLED")
                missing_packages.append(package)

    if missing_packages:
        print(f"\n{YELLOW}Run: pip install -r requirements.txt{RESET}")
        return False

    return True


def check_project_imports():
    """Check if project modules can be imported"""
    print_header("Project Module Import Check")

    # Add project root to path
    sys.path.insert(0, str(Path.cwd()))

    modules_to_check = [
        ('config.settings', 'Configuration'),
        ('src.core.data_fetcher', 'Data Fetcher'),
        ('src.core.structure_detector', 'Structure Detector'),
        ('src.core.order_block_detector', 'Order Block Detector'),
        ('src.core.fvg_detector', 'FVG Detector'),
        ('src.core.liquidity_detector', 'Liquidity Detector'),
        ('src.core.sar_detector', 'SAR Detector'),
        ('src.core.pattern_detector', 'Pattern Detector'),
        ('src.methods.combined_method', 'Combined Method'),
        ('src.methods.percentage_method', 'Percentage Method'),
        ('src.methods.liquidity_sar_method', 'Liquidity SAR Method'),
        ('src.indicators.guardeer', 'Guardeer Indicator'),
        ('src.indicators.smart_money', 'Smart Money Concepts'),
        ('src.integrations.telegram_bot', 'Telegram Bot'),
        ('src.integrations.chart_generator', 'Chart Generator'),
        ('src.integrations.claude_vision', 'Claude Vision'),
        ('src.utils.logger', 'Logger'),
        ('src.utils.timeframe_utils', 'Timeframe Utils'),
        ('src.utils.confluence_scorer', 'Confluence Scorer'),
    ]

    failed_imports = []
    for module, description in modules_to_check:
        try:
            __import__(module)
            print_success(f"{description:30s} - {module}")
        except Exception as e:
            print_error(f"{description:30s} - {module}")
            print(f"           Error: {str(e)}")
            failed_imports.append((module, str(e)))

    return len(failed_imports) == 0


def check_csv_data():
    """Check if CSV data files are present"""
    print_header("Historical Data Check")

    data_dir = Path('data/historical')
    required_timeframes = ['M5', 'M15', 'M30', 'H1', 'H4', 'D1', 'W1', 'MN']

    if not data_dir.exists():
        print_error("data/historical/ directory not found")
        return False

    all_present = True
    for tf in required_timeframes:
        csv_file = data_dir / f'XAUUSD_{tf}.csv'
        if csv_file.exists():
            # Check file size
            size_kb = csv_file.stat().st_size / 1024
            print_success(f"XAUUSD_{tf}.csv ({size_kb:.1f} KB)")
        else:
            print_error(f"XAUUSD_{tf}.csv - MISSING")
            all_present = False

    return all_present


def check_configuration():
    """Check configuration files"""
    print_header("Configuration Check")

    # Check .env file
    env_template = Path('config/.env.template')
    env_file = Path('config/.env')

    if env_template.exists():
        print_success(".env.template exists")
    else:
        print_error(".env.template missing")

    if env_file.exists():
        print_success(".env file exists")

        # Check for placeholder values
        with open(env_file, 'r') as f:
            content = f.read()
            if 'your_telegram_bot_token_here' in content:
                print_warning("Telegram bot token not configured (required for live bot)")
            else:
                print_success("Telegram bot token configured")

            if 'your_claude_api_key_here' in content:
                print_warning("Claude API key not configured (optional - for Vision features)")

            if 'your_twelve_data_api_key_here' in content:
                print_warning("Twelve Data API key not configured (optional - fallback data source)")
    else:
        print_warning(".env file not found - copy from .env.template and configure")

    # Check settings.py
    try:
        from config.settings import settings
        print_success("settings.py loaded successfully")

        print(f"\n  Configuration values:")
        print(f"    Scan interval: {settings.SCAN_INTERVAL_MINUTES} minutes")
        print(f"    Log level: {settings.LOG_LEVEL}")
        print(f"    Min confluence (Method 1): {settings.MIN_CONFLUENCE_SCORE_METHOD1}")
        print(f"    Min confluence (Method 2): {settings.MIN_CONFLUENCE_SCORE_METHOD2}")
        print(f"    Min confluence (Method 3): {settings.MIN_CONFLUENCE_SCORE_METHOD3}")

    except Exception as e:
        print_error(f"Failed to load settings: {e}")
        return False

    return True


def check_directories():
    """Check if required directories exist or create them"""
    print_header("Directory Structure Check")

    required_dirs = [
        'logs',
        'charts',
        'data/historical',
    ]

    for dir_path in required_dirs:
        path = Path(dir_path)
        if path.exists():
            print_success(f"{dir_path}/ exists")
        else:
            try:
                path.mkdir(parents=True, exist_ok=True)
                print_success(f"{dir_path}/ created")
            except Exception as e:
                print_error(f"Failed to create {dir_path}/: {e}")

    return True


def run_verification():
    """Run all verification checks"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{'XAUUSD Trading Bot - Verification Script':^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

    results = {
        'File Structure': check_file_structure(),
        'Directories': check_directories(),
        'Python Packages': check_python_imports(),
        'Project Modules': check_project_imports(),
        'CSV Data': check_csv_data(),
        'Configuration': check_configuration(),
    }

    # Summary
    print_header("Verification Summary")

    all_passed = True
    for check_name, passed in results.items():
        if passed:
            print_success(f"{check_name}")
        else:
            print_error(f"{check_name}")
            all_passed = False

    print(f"\n{BLUE}{'='*60}{RESET}")
    if all_passed:
        print(f"{GREEN}✓ All checks passed! Bot is ready to run.{RESET}")
        print(f"\n{BLUE}Next steps:{RESET}")
        print(f"  1. Configure config/.env with your API keys")
        print(f"  2. Run: python scripts/preprocess_csv.py")
        print(f"  3. Run: python scripts/backtest.py --csv-data")
        print(f"  4. Run: python src/main.py (for live bot)")
    else:
        print(f"{RED}✗ Some checks failed. Please fix the issues above.{RESET}")
        print(f"\n{BLUE}Common fixes:{RESET}")
        print(f"  • Missing packages: pip install -r requirements.txt")
        print(f"  • Missing .env: copy config/.env.template to config/.env")
        print(f"  • Missing CSV data: check data/historical/ directory")
    print(f"{BLUE}{'='*60}{RESET}\n")

    return all_passed


if __name__ == '__main__':
    try:
        success = run_verification()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print(f"\n\n{YELLOW}Verification interrupted by user{RESET}")
        sys.exit(1)
    except Exception as e:
        print(f"\n{RED}Verification failed with error:{RESET}")
        print(f"{RED}{str(e)}{RESET}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
