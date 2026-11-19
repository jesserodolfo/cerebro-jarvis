# Roadmap

Work I plan to do on Jarvis (estimated 40+ hours).

## Code quality
- [ ] Unit tests for `_base.py` and every collector, with recorded sample responses (6 h)
- [ ] Move hard-coded local paths into `config.json`, so the project runs on any machine (3 h)
- [ ] One setup script for macOS (launchd) and Linux (systemd) (4 h)

## Features
- [ ] Weekly report: export the dashboard state to Markdown/PDF every Sunday (4 h)
- [ ] Alerts: send failed jobs and important changes to a private Telegram bot (4 h)
- [ ] YouTube: add watch time and retention per video to the YouTube collector (5 h)
- [ ] Agenda: drag a post to another day and sync it back to the scheduler (6 h)
- [ ] Second Brain: search and tags for saved notes (4 h)
- [ ] Voice: provider plugin interface, so a new TTS engine is one file (3 h)

## Front end
- [ ] Mobile layout and accessibility pass on the dashboard (4 h)
- [ ] Charts for metrics history (followers, views, failures per week) (4 h)
