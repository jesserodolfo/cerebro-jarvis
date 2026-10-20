# Painel Jarvis: voz, Second Brain e visão de todos os projetos

Data: 2026-10-20. Aprovado pelo Jessé (plano Prumo com GO).

## Contexto
O Jessé quer uma página única com voz que mostre todos os projetos (TikTok, Instagram,
YouTube e Facebook do Jesus é Pop, sites, agentes, notícias) e responda conhecendo a vida
dele. O prompt de origem gerava um HTML isolado, que não enxerga arquivo nem banco local.

## Decisão
- HTML único (`painel/index.html`) servido por `painel/servidor.py` (só biblioteca padrão)
  em 127.0.0.1:8790, com launchd próprio (`com.jarvis.painel`).
- Cérebro: API da Anthropic direta, chamada pelo servidor, em streaming (fala frase
  a frase). Chave em `painel/.env` (ANTHROPIC_API_KEY), fora do git, nunca no
  navegador. Modo rápido claude-haiku-5-5 (voz); "pensa melhor" claude-opus-5-5 com
  fallback de recusa (server-side-fallback-2026-07-01). Cache de prompt em 2 blocos
  (notas+regras; estado dos projetos), hora atual fora do cache.
- Card de Custos: consumo do Claude Code por projeto na semana do plano, lido dos
  logs locais, contra fatias em `painel/config.json`.
- Segurança local: servidor recusa Host diferente de 127.0.0.1/localhost:8790,
  Origin de outro site e POST sem JSON.
- Python do serviço: venv próprio em `painel/.venv` (3.14). O 3.15 do Homebrew ficou
  travado esperando a permissão do macOS pra pasta Documentos.
- Dados lidos direto da fonte, só leitura: `Jesusepop/jarvis_yt.db` (mode=ro),
  `tiktok-video-ia/`, `fabrica-conteudo/posts/`, Zernio só GET, pastas de sites.
- Notícias: Google News RSS, temas IA e Claude + marketing e TikTok Shop.
- Second Brain em `painel/notas.json` (fora do git). `[[SAVE]]` grava só ali.

## Descartado
- Hermes como cérebro: o Jessé não quer usar o Hermes no painel.
- `claude -p`: 5 a 10 s por resposta; a API responde em 1 a 3 s.
- Chave no localStorage do navegador: expõe a chave e não serve ao servidor.
- Notas no localStorage: somem ao limpar o navegador e o Jarvis do Telegram não lê.
- Notas embutidas no index.html (como o prompt de origem pedia): o index.html vai
  pro GitHub e as notas têm dado pessoal.
- Sonnet 5.5 como modelo único: Haiku é mais rápido pra voz e o Opus cobre o modo profundo.
- Ler a tela da 8787: o `dashboard.py` fica intocado e vira só link.
- Flask ou qualquer pip: mesmo padrão do `dashboard.py`, sem dependência.

## Consequências
- O Jarvis do Telegram (Hermes) continua ligado e independente.
- Notas sem pasta local (Mordomo Invest, Agente Opções, Ironman, Clone Voomi) ficam só
  no grafo, sem card de dados.
- O painel nunca publica nada. Não existe rota de escrita no Zernio.
