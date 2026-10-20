# Voz do painel Jarvis: Kokoro 82M local

Data: 2026-10-20. Aprovado pelo Jessé (plano Prumo com GO): "GO no Kokoro como está:
kokoro-onnx no venv 3.14, int8 primeiro, serviço separado com.jarvis.voz, sem efeito de eco por
enquanto. Pode instalar os pacotes e baixar os 2 arquivos do modelo."
Escolha do motor, nas palavras dele: "Vai de (a): Kokoro direto no painel, voz pt-BR masculina,
e a voz do navegador de reserva."

## Contexto
O ElevenLabs saiu: o Jessé não paga mais o plano. A voz precisa ser gratuita, local, em pt-BR
masculina e caber num M1 de 8 GB que já travou com o Qwen 1.7B do voicebox em 07/10.

## Decisão
- Motor: `kokoro-onnx` (MIT) com o modelo Kokoro 82M (Apache 2.0), `lang` pt-br, vozes `pm_alex`
  e `pm_santa` (o Jessé escolhe pelo som). Instalado no `painel/.venv` (Python 3.14) com
  `--ignore-requires-python`: o pacote declara Python abaixo de 3.14, mas onnxruntime, numpy e
  espeakng-loader têm pacote pronto pro 3.14 no M1.
- Modelo: `kokoro-v1.0.int8.onnx` (92 MB) + `voices-v1.0.bin` (28 MB) em `painel/modelos/`, fora do
  git. O fp16 só entra se o int8 soar mal.
- Serviço separado `com.jarvis.voz` em 127.0.0.1:8791, mesmo `.venv`. Carrega o modelo uma vez ao
  subir e aquece com uma frase. Uma síntese por vez.
- Provedor plugável: `config.json/voz.provedor` escolhe `voz_<provedor>.py` no servidor
  (`kokoro`, `elevenlabs` parado, `nenhum`). A rota `POST /api/voz` e o front não mudam de contrato.
- Front: prazo de 3 s por frase; falhou ou demorou, aquela frase sai pela voz do navegador.
- Sem efeito de eco ou brilho na voz por enquanto.

## Descartado
- Pacote oficial `kokoro`: exige Python abaixo de 3.13 e traz o PyTorch (pesado pra 8 GB).
- Venv novo com Python 3.12: outro executável, o macOS pediria de novo a liberação da pasta
  Documentos (a mesma que travou em 20/10).
- Kokoro dentro do processo do painel: se travar ou estourar memória, derruba o painel junto.
- Modelo fp32 (326 MB): RAM livre de cerca de 1,1 GB com o Chrome aberto.
- voicebox: sem streaming e travou o Mac em 07/10. edge-tts: online e interface não oficial.
- Voz de comunidade que imite ator (Jarvis do filme, Tony Stark): recusado.

## Consequências
- O painel deixa de ser "só biblioteca padrão" no serviço de voz; o `servidor.py` continua sem pip.
- Desligar só a voz: `launchctl bootout gui/$(id -u)/com.jarvis.voz`. O painel segue com a voz
  do navegador.
