# Thin wrapper around tasks.py so the same commands work on Windows (python tasks.py <target>).
PY ?= python

.PHONY: setup data dev api web test lint fmt gen-api backtest train

setup:   ; $(PY) tasks.py setup
data:    ; $(PY) tasks.py data
dev:     ; $(PY) tasks.py dev
api:     ; $(PY) tasks.py api
web:     ; $(PY) tasks.py web
test:    ; $(PY) tasks.py test
lint:    ; $(PY) tasks.py lint
fmt:     ; $(PY) tasks.py fmt
gen-api: ; $(PY) tasks.py gen-api
backtest: ; $(PY) tasks.py backtest
train:   ; $(PY) tasks.py train
