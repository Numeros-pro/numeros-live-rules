# Numeros Live Rules

Public, read-only verified rule data for Numeros calculators.

This repository intentionally contains only public rules and the updater workflow. The main `Numeros-pro/numeros-project` repository stays private.

## FEIE data

The calculator reads `feie.json` through GitHub Pages.

A scheduled GitHub Action checks the official IRS FEIE guidance and the official U.S. Code Section 911 text. Routine annual ceiling changes update automatically. If the operative Section 911 text changes, the feed switches to `review-required` so the calculator can pause instead of silently applying stale tax logic.

## Safety

- No GitHub token is exposed to Blogger visitors.
- Unknown future values are never guessed.
- Existing verified data remains available if a scheduled check fails.
- Structural tax-law changes require review before new calculation logic is trusted.
