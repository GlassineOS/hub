# SPDX-License-Identifier: GPL-2.0-or-later
PYTHON ?= python3
NODE ?= node

.PHONY: check
check:
	$(NODE) --check app/hub/static/app.js
	$(PYTHON) -m pytest -q
