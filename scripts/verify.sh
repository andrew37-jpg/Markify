#!/bin/sh
set -e
python -m compileall -q app scripts tests
python -m pytest -q
