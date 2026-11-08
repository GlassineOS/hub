# SPDX-License-Identifier: GPL-2.0-or-later
PYTHON ?= python3
NODE ?= node

.PHONY: check
check:
	$(NODE) --check app/hub/static/app.js
	$(PYTHON) -m pytest -q

# The design boards (design/): GlassineOS/ui's tools and Interleaf, at this one pinned version.
UI_REF = v1.1.0
UI = $(HOME)/.cache/glassine/ui/$(UI_REF)
# Checks run in Alpine with the pinned Chromium. CI is already inside that container and sets this empty.
IN_ALPINE = $(UI)/tools/in-alpine

$(UI):
	git clone -q https://github.com/GlassineOS/ui $@
	git -C $@ checkout -q $(UI_REF)

.PHONY: boards-ui boards-preview boards-check boards-references boards-references-update
boards-ui: | $(UI)
	@echo $(UI)
boards-preview: | $(UI)
	$(UI)/tools/boards preview design
boards-check: | $(UI)
	$(IN_ALPINE) $(UI)/tools/boards check design
boards-references: | $(UI)
	$(IN_ALPINE) $(UI)/tools/boards references design
boards-references-update: | $(UI)
	$(IN_ALPINE) $(UI)/tools/boards references design --update
