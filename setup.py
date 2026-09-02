from setuptools import setup, find_packages

setup(
    name="xauusd-trading-bot",
    version="0.1.0",
    description="Automated XAUUSD trading analysis bot with three distinct methodologies",
    author="Trading Team",
    packages=find_packages(),
    install_requires=[
        "yfinance>=0.2.40",
        "pandas>=2.2.0",
        "numpy>=1.26.0",
        "ta>=0.11.0",
        "scipy>=1.13.0",
        "python-telegram-bot>=21.0",
        "requests>=2.31.0",
        "anthropic>=0.34.0",
        "matplotlib>=3.8.0",
        "mplfinance>=0.12.10b0",
        "plotly>=5.18.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0.1",
        "schedule>=1.2.0",
        "pytz>=2024.1",
        "colorlog>=6.8.0",
        "pytest>=8.0.0",
        "pytest-cov>=4.1.0",
        "pytest-mock>=3.12.0",
        "tqdm>=4.66.0"
    ],
    python_requires=">=3.10",
    entry_points={
        'console_scripts': [
            'xauusd-bot=src.main:main',
        ],
    },
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Financial and Insurance Industry",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
