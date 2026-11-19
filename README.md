# Jarvis: personal voice dashboard for a solo creator

Jarvis is my personal command center. It runs on my Mac, collects the status of all my content channels and automations, and shows everything in one local dashboard that I can also talk to by voice.

I use it every day to check my TikTok, Instagram and YouTube channels, see what is scheduled for the week, follow my automation jobs, and ask questions out loud ("how did my reels do this week?").

## What it does

- **Dashboard** (`painel/`): a local web page served by `servidor.py` on `127.0.0.1:8790`, with tabs for projects, agenda and agents.
- **Collectors** (`painel/coletores/`): small read-only Python scripts, one per source (TikTok, Instagram, YouTube, sites, automation agents, costs, news). Each one returns a small JSON card. Rules are in `painel/CONTRATO.md`.
- **Voice**: local text-to-speech with Kokoro (`voz_kokoro.py`), with ElevenLabs as an optional provider.
- **Actions**: a closed list of actions in `painel/config.json` (for example, re-run a data collection). They only run after I confirm in the dashboard.
- **Skills** (`skills/`): prompts for the agent side (morning content ideas, Instagram metrics, competitor radar, reels scripts, carousel, feedback log).
- **Scripts** (`scripts/`): metrics extraction and setup helpers.
- **Decisions** (`docs/decisoes/`): short records of every important design decision.

## Built with

Python 3 (standard library only for the server and collectors), plain HTML/CSS/JS for the front end, Kokoro TTS, macOS launchd services, and the Zernio API (read-only) for social media metrics.

## How to run

```bash
cp .env.example painel/.env      # fill in your own keys
python3 painel/servidor.py       # then open http://127.0.0.1:8790
```

To run it as a background service on macOS, adapt and load the `painel/*.plist` files with `launchctl`.

## Status

Active personal project. Planned work is listed in [ROADMAP.md](ROADMAP.md).

## License

MIT, see [LICENSE](LICENSE).
