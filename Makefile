PYTHON ?= python

.PHONY: install test backtest lint

install:
	$(PYTHON) -m pip install --upgrade pip
	$(PYTHON) -m pip install -e .[dev]

test:
	$(PYTHON) -m pytest

backtest:
	$(PYTHON) -m research.backtest --symbol BTCUSDT --timeframe 1h --limit 180

lint:
	$(PYTHON) -m compileall src tests
