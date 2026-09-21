# Prompt para o Claude Code colocar o Jarvis no ar
Cole no Claude Code, com esta pasta cerebro-jarvis aberta.

---

Vamos colocar no ar meu agente Jarvis, rodando Hermes Agent na minha VPS da
Hostinger. O cérebro dele é esta pasta. Siga na ordem e pare em cada ponto
marcado com PARE.

REGRAS DA SESSÃO
- Mostre cada comando e o que ele faz antes de rodar.
- A VPS tem operação em produção (MelaVitta, n8n). Nada dela é parado,
  movido, reiniciado ou alterado. Se algum passo exigir, PARE e pergunte.
- Eu digito senha, token e chave. Nunca peça para eu colar segredo no chat.
- Para qualquer caminho, comando ou campo do Hermes, consulte a
  documentação oficial em hermes-agent.nousresearch.com/docs ou pergunte ao
  próprio Hermes. Não invente.

ETAPA 1: SUBIR O CÉREBRO (no meu computador)
1. Leia README.md e mapa.md desta pasta para entender a estrutura.
2. Confira se não há nenhuma chave, token ou senha em nenhum arquivo.
3. Rode scripts/subir-cerebro.sh.
PARE: me peça para conferir o repositório no navegador.

ETAPA 2: CÉREBRO NA VPS
1. Conecte na VPS e confirme como o Hermes foi instalado: direto no sistema
   ou em Docker. Me diga qual.
2. Entre como o usuário do agente (não root) e rode
   scripts/instalar-na-vps.sh. Ele vai mostrar uma chave pública.
PARE: eu cadastro a deploy key no GitHub e aviso.
3. Se o Hermes estiver em Docker, monte ~/cerebro dentro do container como
   volume de leitura e escrita. Mostre o comando antes. PARE antes de recriar
   qualquer container.

ETAPA 3: IDENTIDADE E SKILLS
1. Pergunte ao Hermes onde ficam: o arquivo de identidade, o diretório de
   skills e a configuração de base de conhecimento. Me mostre as respostas.
2. Faça cópia do arquivo de identidade atual com o nome soul-original.md.
3. Substitua pelo conteúdo de ~/cerebro/SOUL.md.
4. Instale as 6 skills de ~/cerebro/skills/ no diretório de skills do Hermes,
   no formato que ele espera. Se o formato for diferente de SKILL.md com
   cabeçalho name e description, adapte sem mudar o conteúdo e me diga o que
   adaptou.
5. Configure ~/cerebro como diretório de trabalho ou base de conhecimento.
6. No setup: limiar de compactação de memória em 0.8.
PARE: me mostre o estado antes de seguir.

ETAPA 4: LIMITE DE MEMÓRIA
Configure teto de memória de cerca de 2,5 GB para o agente. Em serviço do
sistema, via MemoryMax. Em Docker, no container. Me explique como reverter.

ETAPA 5: TELEGRAM
1. Me oriente a colar o token do bot direto no terminal, no gateway.
2. Configure para responder SOMENTE ao meu usuário do Telegram.
PARE: eu mando "oi" pelo celular e confirmo.

ETAPA 6: TESTE DO CÉREBRO
Pelo Telegram, eu vou pedir a pauta-matinal. Você não interfere.
PARE: a sessão termina aqui. Nenhum cron é criado hoje.

FECHAMENTO
Escreva ~/cerebro/ESTADO.md com: como o Hermes está instalado, onde está
cada coisa, como reiniciar o agente, como reverter o limite de memória e o
que ficou pendente. Faça commit e push.

O QUE NÃO FAZER HOJE
Cron, postagem automática, WhatsApp, qualquer acesso à operação.
