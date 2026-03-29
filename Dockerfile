FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
COPY .env.example ./

RUN python -m pip install --upgrade pip \
    && python -m pip install -e .[dev]

CMD ["python", "-m", "research.backtest", "--symbol", "BTCUSDT", "--timeframe", "1h", "--limit", "180"]
