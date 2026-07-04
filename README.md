Here you go — full rewrite, in plain Portuguese, written for someone who has never opened a terminal before. I pulled the current README content first so nothing existing gets lost, and folded in every new behavior we added (the letterbox warning, --preview, --force, --check, minimum-length check) with the actual translated error messages so people can search/match them directly.
Copy everything inside the block below and paste it as the full content of README.md:
markdown# pyBRAS-DCP-converter

Este programa transforma um vídeo em um arquivo de áudio especial (`.wav`) que pode ser usado no **Canal 15** de um DCP. Foi criado para permitir a inclusão do canal de **Libras** em exibições de cinema.

Você **não precisa saber programar** para usar este programa. Este guia foi escrito pensando em quem nunca usou um terminal antes — siga os passos na ordem e vai funcionar.

---

## O que esse programa faz, em resumo

Você tem um vídeo com um(a) intérprete de Libras. O programa converte esse vídeo em um arquivo `.wav` especial, que **não é um áudio normal** — é um vídeo disfarçado de áudio, para que o projetor de cinema consiga exibi-lo no Canal 15 junto com o filme.

Você entrega o `.wav` gerado para quem está montando o DCP do filme. Não é necessário entender os detalhes técnicos por trás disso.

---

## Antes de começar: como deve ser o vídeo

Isso é importante e evita retrabalho depois.

- **Formato do arquivo:** `.mp4` ou `.mov` funcionam bem. A maioria dos vídeos gravados em celular já está em um desses formatos.
- **Formato da imagem (proporção):** o ideal é um vídeo **na vertical**, parecido com a proporção de um Story do Instagram ou de um vídeo de celular gravado na posição vertical (mais alto do que largo). Se o vídeo do(a) intérprete foi gravado na horizontal (like uma gravação de câmera de reunião ou webcam widescreen), o programa ainda vai funcionar, mas vai **avisar você** antes de continuar — veja a seção [Se aparecer um aviso sobre o formato do vídeo](#se-aparecer-um-aviso-sobre-o-formato-do-vídeo) mais abaixo.
- **Duração mínima:** pelo menos 2 segundos. Vídeos mais curtos que isso não podem ser convertidos.
- **Nome do arquivo:** evite espaços e acentos no nome do vídeo, se possível. Por exemplo, prefira `video_libras.mp4` em vez de `vídeo do intérprete final v2.mp4`. Não é obrigatório, mas evita dor de cabeça.

---

## Requisitos

- Um computador (Windows ou Mac).
- O arquivo do programa: `encode_slv_wav.py`.
- O vídeo a ser convertido.
- Python e FFmpeg instalados (passo a passo abaixo — só precisa fazer isso **uma vez** no computador).

---

## Instalação (só precisa fazer isso uma vez)

### Windows

1. Acesse <https://www.python.org/downloads/> e instale o Python.
2. **Importante:** na primeira tela do instalador, marque a caixinha **"Add Python to PATH"** antes de clicar em instalar. Se você esquecer esse passo, vai precisar desinstalar e instalar de novo.
3. Abra o **Windows PowerShell** (procure por "PowerShell" no menu Iniciar).
4. Digite o comando abaixo e aperte Enter:
winget install ffmpeg

### Mac

1. Abra o aplicativo **Terminal** (procure por "Terminal" no Spotlight, com Cmd+Espaço).
2. Instale o Homebrew (um instalador de programas para Mac) colando este comando e apertando Enter:
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
3. Depois que terminar, instale o Python e o FFmpeg com:
brew install python ffmpeg

Se algum desses comandos der erro, veja a tabela de [Solução de Problemas](#solução-de-problemas) no fim deste guia.

---

## Como converter um vídeo — passo a passo

1. Crie uma pasta nova no seu computador (pode chamar de "Conversao Libras", por exemplo).
2. Coloque dentro dessa pasta **dois arquivos**: o `encode_slv_wav.py` e o vídeo em Libras que você quer converter.
3. Abra o terminal **dentro dessa pasta**:
   - **Windows:** abra a pasta no Explorador de Arquivos, segure Shift e clique com o botão direito em um espaço vazio da pasta, e escolha "Abrir janela do PowerShell aqui" (ou "Abrir no Terminal", dependendo da versão do Windows).
   - **Mac:** abra o Terminal normalmente e arraste a pasta para dentro da janela do Terminal — isso preenche o caminho da pasta automaticamente. Depois aperte Enter.
4. Digite o comando de conversão, trocando `video_libras.mp4` pelo nome real do seu arquivo de vídeo (se o nome tiver espaços, coloque-o entre aspas):

   - **Windows:**
 python encode_slv_wav.py video_libras.mp4
   - **Mac:**
 python3 encode_slv_wav.py video_libras.mp4

5. Aperte Enter e aguarde. Você vai ver algo assim na tela:
Codificando video_libras.mp4
vídeo forçado:      24 fps, 480x640, VP9 @ 576000 bps
duração do bloco:   2s = 48 frames = 288000 bytes
PCM de saída:       24-bit / 48000 Hz / 1 canal
Sucesso! video_libras.wav foi gravado (use este arquivo no canal 15 de áudio do DCP)
OK: video_libras.wav — 4 bloco(s) de 288000 bytes, ~8s de vídeo, 48000 Hz / 24-bit / 1 canal PCM
   A tela pode ficar "parada" por um tempo em vídeos longos — isso é normal, é o computador processando o vídeo.

6. Quando aparecer a linha começando com **"Sucesso!"** seguida de uma linha começando com **"OK:"**, terminou. O arquivo `.wav` vai estar na mesma pasta, pronto para ser entregue a quem está montando o DCP.

   A linha "OK:" é uma segunda checagem automática que o programa faz para confirmar que o arquivo saiu certinho — se você vir "Sucesso!" mas depois "FALHOU:", algo deu errado na etapa final; veja a tabela de problemas abaixo.

---

## Se aparecer um aviso sobre o formato do vídeo

Se o vídeo enviado pelo(a) intérprete não estiver próximo do formato vertical exigido, você vai ver algo assim antes da conversão começar:
aviso: a origem é 1920x1080; para encaixá-la no quadro retrato exigido de 480x640 sem
distorcer a imagem, ela será reduzida para apenas 480x270 e receberá tarjas pretas
(letterbox) — cobrindo somente 42% do quadro.
O(a) intérprete pode aparecer pequeno(a) e difícil de ver. Considere recortar a origem
para uma proporção próxima de 3:4 (retrato) antes de codificar.

**O que isso significa, em português simples:** o vídeo que você recebeu é "deitado" (horizontal) ou tem um formato muito diferente do exigido pelo Canal 15. O programa consegue converter mesmo assim, mas vai colocar tarjas pretas nas bordas para não distorcer a imagem — e dependendo de quão diferente for o formato, o(a) intérprete pode aparecer bem pequeno(a) no resultado final.

Você tem três opções:

1. **Pedir um novo vídeo** para quem gravou, orientando a gravar na vertical (como um vídeo de celular seguro na posição de pé, ou como um Story do Instagram). Essa é a melhor opção quando dá tempo.
2. **Conferir antes de decidir**, rodando o comando abaixo — ele não converte nada, só gera uma foto (`.jpg`) mostrando exatamente como vai ficar o quadro final:
python encode_slv_wav.py video_libras.mp4 --preview
   (No Mac, use `python3` em vez de `python`.) Abra a imagem gerada (vai se chamar `video_libras.preview.jpg`, na mesma pasta) para ver se o(a) intérprete ainda está visível o suficiente.
3. **Seguir em frente mesmo assim**, se o resultado do preview estiver aceitável, adicionando `--force` ao final do comando de conversão:
python encode_slv_wav.py video_libras.mp4 --force

Se você rodar o comando normal (sem `--force`) e o terminal perguntar `Continuar mesmo assim, com letterbox pesado? [s/N]:`, digite `s` e aperte Enter para continuar, ou apenas aperte Enter para cancelar.

---

## Conferir se um arquivo `.wav` já pronto está correto

Se você já tem um arquivo `.wav` (gerado por este programa ou recebido de outra pessoa) e quer confirmar que ele está no formato certo, sem gerar um novo:
python encode_slv_wav.py --check video_libras.wav

Se estiver tudo certo, você verá uma linha começando com `OK:`. Se houver um problema, verá uma linha começando com `FALHOU:` explicando o que está errado.

---

## Solução de Problemas

| Mensagem que apareceu | O que significa e como resolver |
| --- | --- |
| `'python' não é reconhecido` | O Python não foi instalado corretamente, ou a caixinha "Add Python to PATH" não foi marcada. Reinstale o Python marcando essa opção. |
| `'ffmpeg' não é reconhecido` | Feche e abra o terminal de novo (às vezes resolve sozinho). Se persistir, reinstale o FFmpeg seguindo os passos de instalação acima. |
| `erro: ferramenta obrigatória 'ffprobe' não encontrada no PATH` | O FFmpeg não foi instalado corretamente — o `ffprobe` vem junto com ele. Reinstale o FFmpeg. |
| `erro: [arquivo] já existe, abortando` | Já existe um `.wav` com esse nome nessa pasta. Apague-o, renomeie-o, ou rode o comando de novo usando `-o outronome.wav` para escolher outro nome de saída. |
| `erro: [arquivo]: arquivo não encontrado` | O nome do vídeo foi digitado errado, ou o vídeo não está na mesma pasta que o `encode_slv_wav.py`. Confira o nome exato do arquivo (no Windows, ative "mostrar extensões de arquivo" nas opções do Explorador de Arquivos para ver o `.mp4` no fim do nome). |
| `erro: a origem tem [x]s de duração, menos que um bloco de 2s` | O vídeo é curto demais (menos de 2 segundos). Use um vídeo mais longo. |
| `erro: [arquivo] não contém nenhuma trilha de vídeo (ou o arquivo está corrompido/ilegível)` | O arquivo enviado não é um vídeo válido, ou está corrompido. Peça o arquivo novamente para quem enviou. |
| Aparece um `aviso:` sobre "letterbox" e uma pergunta `[s/N]` | O vídeo não está no formato vertical esperado. Veja a seção [Se aparecer um aviso sobre o formato do vídeo](#se-aparecer-um-aviso-sobre-o-formato-do-vídeo) acima. |
| A tela fica "travada" por um tempo | É normal em vídeos longos — apenas espere. Só se preocupe se passarem muitos minutos sem nenhuma mudança. |
| Aparece `Sucesso!` mas depois `FALHOU:` | A conversão terminou mas a checagem final encontrou um problema no arquivo gerado. Tente rodar de novo; se persistir, guarde a mensagem completa de erro para pedir ajuda. |

---

## Glossário rápido

- **DCP:** o formato de arquivo usado para exibir filmes em cinemas digitais.
- **Canal 15:** uma trilha extra dentro do DCP reservada para conteúdo de acessibilidade, como o vídeo de Libras.
- **Libras:** Língua Brasileira de Sinais.
- **Terminal / Prompt de Comando:** um programa onde você digita comandos de texto em vez de clicar em botões — é assim que este conversor é usado, já que ele não tem uma tela com botões.
- **`.wav`:** neste caso, não é um áudio de verdade — é um arquivo de vídeo "disfarçado" para caber no formato de áudio exigido pelo Canal 15.
