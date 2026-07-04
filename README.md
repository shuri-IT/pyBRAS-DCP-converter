# pyBRAS-DCP-converter

Este programa transforma um vídeo em um arquivo de áudio especial (`.wav`) que pode ser usado no **Canal 15** de um DCP. Foi criado para permitir a inclusão do canal de **Libras** em exibições de cinema.

Você **não precisa saber programar** para usar este programa. Este guia foi escrito pensando em quem nunca usou um terminal antes — siga os passos na ordem e vai funcionar.

## Índice

- [Créditos](#créditos)
- [Compatibilidade testada](#compatibilidade-testada)
- [Verificação de segurança](#verificação-de-segurança)
- [O que esse programa faz, em resumo](#o-que-esse-programa-faz-em-resumo)
- [Antes de começar: como deve ser o vídeo](#antes-de-começar-como-deve-ser-o-vídeo)
- [Etapa 0 (recomendada): preparar o vídeo em um editor](#etapa-0-recomendada-preparar-o-vídeo-em-um-software-de-edição-premiere-davinci-resolve-after-effects-media-composer-etc-antes-de-converter)
- [Requisitos](#requisitos)
- [Instalação](#instalação-só-precisa-fazer-isso-uma-vez)
  - [Windows](#windows)
  - [Mac](#mac)
- [Como converter um vídeo — passo a passo](#como-converter-um-vídeo--passo-a-passo)
- [Se aparecer um aviso sobre o formato do vídeo](#se-aparecer-um-aviso-sobre-o-formato-do-vídeo)
- [Conferir se um arquivo .wav já pronto está correto](#conferir-se-um-arquivo-wav-já-pronto-está-correto)
- [Solução de Problemas](#solução-de-problemas)
- [Glossário rápido](#glossário-rápido)
- [Para os nerds da codificação 🤓](#para-os-nerds-da-codificação-)
  - [A norma seguida](#a-norma-seguida)
  - [Parâmetros exigidos pela norma](#parâmetros-exigidos-pela-norma)
  - [Como o vídeo VP9 é escondido dentro do WAV](#como-o-vídeo-vp9-é-escondido-dentro-do-wav)
  - [Duas abordagens comuns para implementar essa norma](#duas-abordagens-comuns-para-implementar-essa-norma)
  - [Recapitulando os parâmetros técnicos deste script](#recapitulando-os-parâmetros-técnicos-deste-script)


## Créditos

Este guia foi revisado com a ajuda de **[Eduardo Pires de Vasconcelos](https://www.imdb.com/pt/name/nm10246068/)**, montador, finalizador e coordenador de pós-produção, que ajudou a identificar pontos de confusão no passo a passo e apontou detalhes técnicos de preparo de vídeo (como o processo de remoção de chroma key e exportação) importantes para quem já trabalha profissionalmente com pós-produção.

---

## Compatibilidade testada

Foram feitos DCPs de teste usando os softwares **Easy DCP** e **DCP-o-matic** e, em ambos, o recurso de Libras funcionou corretamente nos pacotes gerados.

---

## Verificação de segurança

O arquivo `pyBRAS_conversor_libras_wav.py` foi verificado no [VirusTotal](https://www.virustotal.com), que analisa o arquivo com dezenas de antivírus diferentes ao mesmo tempo.

- **Resultado:** [0/62 — nenhum antivírus identificou o arquivo como malicioso](https://www.virustotal.com/gui/file/15268e25213cf54b5e546318bb92426e0dce0e7543eea6a7fb190d8dcf2efa23/detection)
- **SHA256 do arquivo verificado:** `15268e25213cf54b5e546318bb92426e0dce0e7543eea6a7fb190d8dcf2efa23`

> Este selo é válido apenas para a versão exata do arquivo com o hash acima (a v1.2.4). Se o `pyBRAS_conversor_libras_wav.py` for atualizado no futuro, uma nova verificação deve ser feita e o link/hash acima atualizado.

## O que esse programa faz, em resumo

Você tem um vídeo com um(a) intérprete de Libras. O programa converte esse vídeo em um arquivo `.wav` especial, que **não é um áudio normal** — é um vídeo disfarçado de áudio, para que dispositivos de acessibilidade dos cinemas consigam exibir LIBRAS junto com o filme.

Você entrega o `.wav` gerado para quem está montando o DCP do filme. Não é necessário entender os detalhes técnicos por trás disso.

---

## Antes de começar: como deve ser o vídeo

Isso é importante e evita retrabalho depois.

- **Formato do arquivo:** `.mp4` ou `.mov` funcionam bem. A maioria dos vídeos gravados em celular já está em um desses formatos.
- **Formato da imagem (proporção):** o ideal é um vídeo **na vertical**, parecido com a proporção de um Story do Instagram ou de um vídeo de celular gravado na posição vertical (mais alto do que largo). Se o vídeo do(a) intérprete foi gravado na horizontal (como uma gravação de câmera de reunião ou webcam widescreen), o programa ainda vai funcionar, mas vai **avisar você** antes de continuar — veja a seção [Se aparecer um aviso sobre o formato do vídeo](#se-aparecer-um-aviso-sobre-o-formato-do-vídeo) mais abaixo.
- **Duração mínima:** pelo menos 2 segundos. Vídeos mais curtos que isso não podem ser convertidos.
- **Nome do arquivo:** evite espaços e acentos no nome do vídeo, se possível. Por exemplo, prefira `video_libras.mp4` em vez de `vídeo do intérprete final v2.mp4`. Não é obrigatório, mas evita dor de cabeça.

---

## Etapa 0 (recomendada): preparar o vídeo em um software de edição (Premiere, DaVinci Resolve, After Effects, Media Composer, etc) antes de converter

O resultado final ficará melhor e com mais controle se o vídeo já for preparado antes de rodar o conversor, em vez de depender dos ajustes automáticos do programa. Esta etapa é **fortemente recomendada** — o script consegue ajustar resolução e taxa de quadros sozinho —, porque dá controle total sobre o enquadramento do(a) intérprete em vez de deixar isso por conta de um ajuste automático.

Passos:

1. Abra o arquivo de vídeo do(a) intérprete de Libras no seu programa de edição.
2. Se o vídeo foi gravado com fundo verde/azul (chroma key), remova o fundo com efeitos do programa (3D Keyer no DaVinci, Color Key no Premiere) e adicione um fundo sólido preto na track anterior à track da Libras (ex. track 1 com o sólido e track 2 com o(a) intérprete de Libras já sem o chroma).
3. Ajuste a resolução da timeline para **480×640**, enquadrando o(a) intérprete manualmente dentro desse quadro. Fazer isso manualmente evita que o conversor precise reduzir a imagem e adicionar tarjas pretas (letterbox/pillarbox) ou cortar a imagem automaticamente depois.
4. Ajuste o fps para **24 fps** e o field order para **progressivo**.
5. Exporte o vídeo seguindo as specs da timeline em **H.264** com bitrate de **1 Mbps** (1.000 kbps).

Depois de exportar esse arquivo, ele já está pronto para seguir para o Passo 1 logo abaixo — o `pyBRAS_conversor_libras_wav.py` vai transformá-lo no `.wav` final. Fazendo esse preparo manualmente, é bem provável que você nunca veja o aviso de "letterbox" mencionado mais adiante neste guia, porque o vídeo já vai entrar no formato certo.

---

## Requisitos

- Um computador (Windows ou Mac).
- O arquivo do programa: `pyBRAS_conversor_libras_wav.py`.
- O vídeo a ser convertido.
- Python e FFmpeg instalados (passo a passo abaixo — só precisa fazer isso **uma vez**
  no computador, nas vezes seguintes você pode começar direto do
  [Como converter um vídeo — passo a passo](#como-converter-um-vídeo--passo-a-passo)).
  O FFmpeg precisa ser a versão 3.2.4 ou mais nova, com suporte a `libvpx-vp9` e ao
  muxer `webm_chunk` — as instalações feitas pelos comandos deste guia (winget e
  Homebrew) já vêm com tudo isso. Só se preocupe com esse detalhe se você instalar
  o FFmpeg por outro caminho (Linux, conda, builds "mínimos" etc.).

---

## Instalação (só precisa fazer isso uma vez)

### Baixar o programa

Antes de instalar o Python e o FFmpeg, baixe os arquivos do programa:

**[⬇ Baixar pyBRAS-DCP-converter (v1.2.4)](https://github.com/shuri-IT/pyBRAS-DCP-converter/archive/refs/tags/v1.2.4.zip)**

Depois de baixar, extraia o arquivo `.zip` (no Windows, clique com o botão direito no arquivo baixado e escolha "Extrair Tudo"; no Mac, basta dar um duplo clique). Isso vai criar uma pasta chamada algo como `pyBRAS-DCP-converter-1.2.4` — dentro dela está o `pyBRAS_conversor_libras_wav.py` que você vai usar mais adiante neste guia.

### Windows

1. Acesse <https://www.python.org/downloads/> e instale o Python.
2. **Importante:** na primeira tela do instalador, marque a caixinha **"Add Python to PATH"** antes de clicar em instalar. Se você esquecer esse passo, vai precisar desinstalar e instalar de novo.
3. Abra o **Windows PowerShell** (procure por "PowerShell" no menu Iniciar).
4. Digite o comando abaixo e aperte Enter: <br> <br>
winget install ffmpeg

### Mac

1. Abra o aplicativo **Terminal** (procure por "Terminal" no Spotlight, com Cmd+Espaço).

   > **Antes de continuar:** em algum momento da instalação abaixo, o Terminal vai pedir sua senha, mostrando algo como `Password:` e uma linha dizendo que está verificando o acesso de administrador (`sudo`). **Isso é normal e esperado, não é vírus nem invasão.** É só a instalação pedindo a senha que você usa para desbloquear o Mac ou instalar aplicativos. Digite sua senha normalmente e aperte Enter — é esperado que **nada apareça na tela** enquanto você digita (nem bolinhas, nem letras), o Terminal esconde a senha por segurança, mas ele está recebendo o que você digita. Se você não sabe a senha de administrador desse computador (por exemplo, é um computador da empresa gerenciado por outra pessoa), pare aqui e peça ajuda a quem administra a máquina, em vez de tentar adivinhar.

2. Instale o Homebrew (um instalador de programas para Mac) colando este comando e apertando Enter: <br> <br>
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" <br> <br>
3. Depois que terminar, instale o Python e o FFmpeg com: <br> <br>
brew install python ffmpeg <br> <br>

Se algum desses comandos der erro, veja a tabela de [Solução de Problemas](#solução-de-problemas) no fim deste guia.

---

## Como converter um vídeo — passo a passo

1. Crie uma pasta nova no seu computador (pode chamar de "Conversao Libras", por exemplo).
2. Coloque dentro dessa pasta **dois arquivos**: o `pyBRAS_conversor_libras_wav.py` e o vídeo em Libras que você quer converter (idealmente já preparado conforme a [Etapa 0](#etapa-0-recomendada-preparar-o-vídeo-em-um-software-de-edição-premiere-davinci-resolve-after-effects-media-composer-etc-antes-de-converter) acima).
3. Abra o terminal **dentro dessa pasta**:
   - **Windows:** abra a pasta no Explorador de Arquivos, segure Shift e clique com o botão direito em um espaço vazio da pasta, e escolha "Abrir janela do PowerShell aqui" (ou "Abrir no Terminal", dependendo da versão do Windows).
   - **Mac:** abra o Terminal normalmente, digite `cd ` (com um espaço depois) e então arraste a pasta para dentro da janela do Terminal — isso preenche o caminho da pasta automaticamente depois do `cd `. Depois aperte Enter. (Se você arrastar a pasta sem digitar o `cd ` antes, vai aparecer um erro do tipo `zsh: permission denied` — é só voltar e digitar o `cd ` no começo da linha.)
4. Digite o comando de conversão, trocando `video_libras.mp4` pelo nome real do seu arquivo de vídeo (se o nome tiver espaços, coloque-o entre aspas como "video com espaco no titulo.mp4"):

   - **Windows:** <br> <br>
 python pyBRAS_conversor_libras_wav.py video_libras.mp4 <br> <br>
   - **Mac:** <br> <br>
 python3 pyBRAS_conversor_libras_wav.py video_libras.mp4 <br> <br>

5. Aperte Enter e aguarde. Você vai ver algo assim na tela:
```
Codificando video_libras.mp4
  vídeo forçado:      24 fps, 480x640, VP9 @ 576000 bps
  duração do bloco:   2s = 48 frames = 288000 bytes
  PCM de saída:       24-bit / 48000 Hz / 1 canal

Sucesso! video_libras.wav foi gravado (use este arquivo no canal 15 de áudio do DCP)
OK: video_libras.wav — 4 bloco(s) de 288000 bytes, ~8s de vídeo, 48000 Hz / 24-bit / 1 canal PCM
```

A tela pode ficar "parada" por um tempo em vídeos longos — isso é normal, é o computador processando o vídeo.

6. Quando aparecer a linha começando com **"Sucesso!"** seguida de uma linha começando com **"OK:"**, terminou. O arquivo `.wav` vai estar na mesma pasta, pronto para ser entregue a quem está montando o DCP.

   A linha "OK:" é uma segunda checagem automática que o programa faz para confirmar que o arquivo saiu certinho — se você vir "Sucesso!" mas depois "FALHOU:", algo deu errado na etapa final; veja a tabela de problemas abaixo.

---

## Se aparecer um aviso sobre o formato do vídeo

Se o vídeo enviado pelo(a) intérprete não estiver próximo do formato vertical exigido — o que não deve acontecer se você seguiu a [Etapa 0](#etapa-0-recomendada-preparar-o-vídeo-em-um-software-de-edição-premiere-davinci-resolve-after-effects-media-composer-etc-antes-de-converter) acima — você vai ver algo assim antes da conversão começar:
```
aviso: a origem é 1920x1080; para encaixá-la no quadro retrato exigido de 480x640 sem
distorcer a imagem, ela será reduzida para apenas 480x270 e receberá tarjas pretas
(letterbox) — cobrindo somente 42% do quadro.
O(a) intérprete pode aparecer pequeno(a) e difícil de ver. Considere recortar a origem
para uma proporção próxima de 3:4 (retrato) antes de codificar.
```
**O que isso significa, em português simples:** o vídeo que você recebeu é "deitado" (horizontal) ou tem um formato muito diferente do exigido pelo Canal 15. O programa consegue converter mesmo assim, mas vai colocar tarjas pretas nas bordas para não distorcer a imagem — e dependendo de quão diferente for o formato, o(a) intérprete pode aparecer bem pequeno(a) no resultado final.

Você tem três opções:

1. **Preparar o vídeo em um editor**, seguindo a [Etapa 0](#etapa-0-recomendada-preparar-o-vídeo-em-um-software-de-edição-premiere-davinci-resolve-after-effects-media-composer-etc-antes-de-converter) no início deste guia — essa é a melhor opção quando dá tempo e há alguém com acesso a um programa de edição.
2. **Conferir antes de decidir**, rodando o comando abaixo — ele não converte nada, só gera uma foto (`.jpg`) mostrando exatamente como vai ficar o quadro final: <br> <br>
python pyBRAS_conversor_libras_wav.py video_libras.mp4 --preview <br> <br>
   (No Mac, use `python3` em vez de `python`.) Abra a imagem gerada (vai se chamar `video_libras.preview.jpg`, na mesma pasta) para ver se o(a) intérprete ainda está visível o suficiente.
3. **Seguir em frente mesmo assim**, se o resultado do preview estiver aceitável, adicionando `--force` ao final do comando de conversão: <br> <br>
python pyBRAS_conversor_libras_wav.py video_libras.mp4 --force

Se você rodar o comando normal (sem `--force`) e o terminal perguntar `Continuar mesmo assim, com letterbox pesado? [s/N]:`, digite `s` e aperte Enter para continuar, ou apenas aperte Enter para cancelar.

---

## Conferir se um arquivo `.wav` já pronto está correto

Se você já tem um arquivo `.wav` (gerado por este programa ou recebido de outra pessoa) e quer confirmar que ele está no formato certo, sem gerar um novo:
<br> <br> python pyBRAS_conversor_libras_wav.py --check video_libras.wav

Se estiver tudo certo, você verá uma linha começando com `OK:`. Se houver um problema, verá uma linha começando com `FALHOU:` explicando o que está errado.

> **Atenção:** se o `.wav` foi gerado com uma duração de bloco diferente do padrão
> (usando a opção `-c`/`--chunk-duration`), você precisa passar o **mesmo valor**
> na hora de conferir — por exemplo, `python pyBRAS_conversor_libras_wav.py --check
> -c 4 video_libras.wav` para um arquivo gerado com blocos de 4 segundos. Sem isso,
> a checagem vai reclamar (erroneamente) do tamanho dos blocos. Se você nunca usou
> a opção `-c`, pode ignorar este aviso.
---

## Solução de Problemas

| Mensagem que apareceu | O que significa e como resolver |
| --- | --- |
| `'python' não é reconhecido`, mas o Python está instalado (Windows) | Em alguns computadores Windows, o comando se chama `py` em vez de `python`. Tente rodar o mesmo comando trocando `python` por `py` (ex.: `py pyBRAS_conversor_libras_wav.py video_libras.mp4`). |
| `erro: nenhum segmento VP9 foi gerado` ou `erro: o ffmpeg não gerou o arquivo de cabeçalho VP9/EBML` | O FFmpeg instalado não tem suporte a VP9 (`libvpx-vp9`) ou ao muxer `webm_chunk` — comum em instalações "mínimas" ou muito antigas do FFmpeg, principalmente fora do winget/Homebrew. Reinstale o FFmpeg seguindo os passos deste guia. |
| `erro: o segmento chunk_XXXXX.chk (... bytes) + cabeçalho EBML (... bytes) excede o tamanho do bloco` | Um trecho do vídeo ficou grande demais para caber no bloco de 2 segundos — raro, porque o bitrate é travado justamente para evitar isso. Tente rodar de novo; se persistir com o mesmo vídeo, guarde a mensagem completa e reporte o problema (veja [Ajuda](#ajuda-e-problemas)). |
| Rodei em um script automático e apareceu `erro: recusando prosseguir de forma não interativa com letterbox pesado` | Quando não há ninguém no teclado para responder à pergunta `[s/N]`, o programa prefere parar a converter um vídeo fora do formato sem confirmação. Confira o enquadramento com `--preview` e, se estiver aceitável, rode de novo adicionando `--force`. |
| `'ffmpeg' não é reconhecido` | Feche e abra o terminal de novo (às vezes resolve sozinho). Se persistir, reinstale o FFmpeg seguindo os passos de instalação acima. |
| Não sei a senha de administrador pedida no `Password:` durante a instalação | Se o computador é da empresa/instituição ou gerenciado por outra pessoa, você pode não ter essa senha — e não deveria tentar adivinhar. Peça para quem administra o computador rodar a instalação, ou peça a senha de administrador a essa pessoa. |
| Toda vez que abro o Terminal aparece uma mensagem tipo `.zprofile:2: no such file or directory: .../brew` | Sobrou uma configuração antiga do Homebrew apontando para um arquivo que não existe mais (geralmente depois de uma instalação que não terminou certo, ou de duas instalações em cima uma da outra). Não afeta o uso deste conversor, mas para limpar: rode `open -e ~/.zprofile`, apague a(s) linha(s) que mencionam `brew shellenv`, salve e feche. Abra um novo Terminal para conferir que a mensagem sumiu. |
| `zsh: unmatched "` ou `zsh: parse error in command substitution` ao colar um comando deste guia | O comando foi corrompido ao ser copiado — geralmente porque foi copiado de um app que reformata o texto (vira um link estilo `[texto](endereço)` em vez do comando puro). Cole o comando primeiro em um editor de texto simples (no Mac, o TextEdit em modo "Texto Sem Formatação", ou o app Notas) para remover qualquer formatação escondida, e só então copie dali para o Terminal. Se preferir, digite o comando manualmente em vez de colar. |
| `zsh: permission denied: /caminho/da/pasta` logo depois de eu abrir o Terminal | Você arrastou a pasta para o Terminal sem digitar `cd ` antes. Digite `cd ` (com espaço) no início da linha, arraste a pasta de novo (ou digite o caminho manualmente) e aperte Enter. |
| `erro: ferramenta obrigatória 'ffprobe' não encontrada no PATH` | O FFmpeg não foi instalado corretamente — o `ffprobe` vem junto com ele. Reinstale o FFmpeg. |
| `erro: [arquivo] já existe, abortando` | Já existe um `.wav` com esse nome nessa pasta. Apague-o, renomeie-o, ou rode o comando de novo usando `-o outronome.wav` para escolher outro nome de saída. |
| `erro: [arquivo]: arquivo não encontrado` | O nome do vídeo foi digitado errado, ou o vídeo não está na mesma pasta que o `pyBRAS_conversor_libras_wav.py`. Confira o nome exato do arquivo (no Windows, ative "mostrar extensões de arquivo" nas opções do Explorador de Arquivos para ver o `.mp4` no fim do nome). |
| `erro: a origem tem [x]s de duração, menos que um bloco de 2s` | O vídeo é curto demais (menos de 2 segundos). Use um vídeo mais longo. |
| `erro: [arquivo] não contém nenhuma trilha de vídeo (ou o arquivo está corrompido/ilegível)` | O arquivo enviado não é um vídeo válido, ou está corrompido. Peça o arquivo novamente para quem enviou. |
| Aparece um `aviso:` sobre "letterbox" e uma pergunta `[s/N]` | O vídeo não está no formato vertical esperado. Veja a seção [Se aparecer um aviso sobre o formato do vídeo](#se-aparecer-um-aviso-sobre-o-formato-do-vídeo) acima — ou faça a [Etapa 0](#etapa-0-recomendada-preparar-o-vídeo-em-um-software-de-edição-premiere-davinci-resolve-after-effects-media-composer-etc-antes-de-converter) da próxima vez para evitar esse aviso. |
| A tela fica "travada" por um tempo | É normal em vídeos longos — apenas espere. Só se preocupe se passarem muitos minutos sem nenhuma mudança. |
| Aparece `Sucesso!` mas depois `FALHOU:` | A conversão terminou mas a checagem final encontrou um problema no arquivo gerado. Tente rodar de novo; se persistir, guarde a mensagem completa de erro para pedir ajuda. |

---

## Glossário rápido

- **DCP:** o formato de arquivo usado para exibir filmes em cinemas digitais.
- **Canal 15:** uma trilha extra dentro do DCP reservada para conteúdo de acessibilidade, como o vídeo de Libras.
- **Libras:** Língua Brasileira de Sinais.
- **Chroma key:** a técnica de gravar sobre um fundo verde ou azul para depois remover esse fundo na edição.
- **Terminal / Prompt de Comando:** um programa onde você digita comandos de texto em vez de clicar em botões — é assim que este conversor é usado, já que ele não tem uma tela com botões.
- **`.wav`:** neste caso, não é um áudio de verdade — é um arquivo de vídeo "disfarçado" para caber no formato de áudio exigido pelo Canal 15.

---

## Para os nerds da codificação 🤓

Esta seção é para quem já trabalha com DCP e quer saber exatamente o que está acontecendo por trás do `Sucesso!`. Se você só precisa converter o vídeo, pode parar de ler aqui.

### A norma seguida

Este conversor implementa o **ISDCF Doc13 — "Sign Language Video Encoding for Digital Cinema"**, o documento técnico que define como um vídeo de intérprete de Libras/sign language deve ser empacotado dentro de uma trilha de áudio PCM para ocupar o Canal 15 de um DCP.

- Documento oficial: <http://isdcf.com/papers/ISDCF-Doc13-Sign-Language-Video-Encoding-for-Digital-Cinema.pdf>
- Implementação de referência (Perl, mantida pela própria ISDCF): <https://github.com/ISDCF/Sign-Language-Video-Encoding>

Este programa é, na prática, uma reimplementação em Python do encoder de referência acima, mantendo os mesmos parâmetros de codificação.

### Parâmetros exigidos pela norma

| Parâmetro | Valor exigido | Observação |
| --- | --- | --- |
| Codec de vídeo | VP9 (`libvpx-vp9`) | Obrigatório pela norma. |
| Resolução | 480×640 (retrato) | Fixa, independente da resolução de origem. |
| Taxa de quadros | 24,0 fps | Forçada mesmo que a origem seja 23.976, 25, 29.97 etc. |
| Formato de pixel | `yuv420p` | — |
| Duração do chunk | 2 segundos | Cada chunk de vídeo VP9 vira um bloco PCM independente. |
| Amostragem PCM | 48.000 Hz | 96 kHz é **proibido** pela norma para este canal. |
| Profundidade PCM | 24-bit | — |
| Canais PCM | 1 (mono) | — |
| Keyframes | 1 por chunk, no início | O script força um keyframe VP9 em cada limite de chunk (`-g` = `keyint_min` = frames por chunk), garantindo que cada bloco PCM seja decodificável de forma independente. |

### Como o vídeo VP9 é escondido dentro do WAV

Cada bloco PCM de 288.000 bytes (48.000 Hz × 24-bit ÷ 8 × 2s) segue este layout binário:
H1 (4 bytes, big-endian) = 0xFFFFFFFF   marcador de sincronismo
Lv (4 bytes, big-endian) = tamanho do segmento VP9 daquele chunk
Lb (4 bytes, big-endian) = tamanho total do bloco (sempre 288.000)
Le (4 bytes, big-endian) = tamanho do cabeçalho EBML/WebM compartilhado
H2 (4 bytes, big-endian) = 0xFFFFFFFF   marcador de sincronismo
E  (Le bytes)            = cabeçalho EBML/WebM (repetido em todo bloco)
V  (Lv bytes)            = segmento VP9 daquele chunk de 2s
P  (resto)               = zeros até completar Lb

### Duas abordagens comuns para implementar essa norma

A ISDCF Doc13 define o resultado final exigido, mas não define como implementar a segmentação do vídeo ou o enquadramento — isso fica a critério de quem programa. Na prática, existem duas abordagens comuns que valem a pena conhecer se você trabalha nessa área:

| Aspecto | Abordagem usada neste conversor | Outra abordagem comum |
| --- | --- | --- |
| Como o VP9 é dividido em chunks de 2s | Usa o muxer `webm_chunk` do próprio ffmpeg, que já entrega o cabeçalho compartilhado e cada segmento separadamente | Codifica o vídeo inteiro primeiro, depois corta com o muxer genérico `segment` e localiza os limites de cada chunk varrendo os bytes brutos em busca do ID de Segment do WebM (`0x18538067`) |
| Controle de taxa de bits (bitrate) | CBR travado: `-b:v`, `-minrate` e `-maxrate` no mesmo valor (576.000 bps), mais `-deadline realtime`, `-static-thresh 0`, `-lag-in-frames 0`, `-error-resilient 1` | Define apenas um bitrate máximo (ex: `-maxrate` sem `-minrate` nem `-bufsize`), com `-deadline good` |
| Enquadramento de vídeos fora da proporção 3:4 | Escala preservando a proporção original e adiciona tarjas pretas (letterbox) até fechar 480×640 | Recorta (crop) as bordas do vídeo para forçar a proporção 3:4 antes de escalar |
| Verificação do arquivo gerado | `--check` / autoverificação embutida no próprio script, reaproveitando as mesmas constantes do encoder | Ferramenta de validação separada, feita depois da codificação |
| Interface | Linha de comando | Aplicativo com interface gráfica |

Nenhuma das duas está "errada" pela norma em si — são escolhas de implementação, cada uma com trade-offs. Usar o `webm_chunk` evita ter que adivinhar limites de bytes no formato WebM em vez de deixar o próprio ffmpeg entregar os chunks já separados. Travar o CBR (`minrate = maxrate`) evita que um chunk de maior movimento gere um segmento VP9 grande demais para caber nos 288.000 bytes fixos do bloco — sem essa trava, o VP9 pode estourar o bitrate médio em cenas mais complexas e o bloco não cabe no tamanho fixo exigido. E optar por letterbox em vez de crop evita cortar parte da imagem do(a) intérprete (mãos, rosto) à custa de tarjas pretas nas bordas.

### Recapitulando os parâmetros técnicos deste script
Codec:            VP9 (libvpx-vp9)
Resolução:        480×640
Taxa de quadros:  24.0 fps (forçada)
Pixel format:     yuv420p
Bitrate:          576.000 bps (CBR travado)
Chunk:            2.0s / 48 frames (configurável via --chunk-duration)
Muxer:            webm_chunk
PCM:              48.000 Hz / 24-bit / mono
Bloco PCM:        288.000 bytes (20 bytes de cabeçalho + E + V + padding)

Flags relevantes para quem for automatizar isso em lote:

- `-c/--chunk-duration`: altera a duração do chunk (padrão 2.0s, conforme a norma —
  só mude se souber o que está fazendo). Se você gerar um `.wav` com valor diferente
  do padrão, precisa passar o mesmo valor ao usar `--check` nele.
- `--check arquivo.wav`: valida um `.wav` já existente sem recodificar. Sai com
  código diferente de zero em caso de falha, então dá para usar direto em scripts/CI.
- `--preview [caminho.jpg]`: gera só o frame de pré-visualização com o mesmo filtro
  de scale/letterbox do encode. O caminho de saída é opcional; sem ele, o padrão é
  `<entrada>.preview.jpg`.
- `--force`: pula a confirmação de letterbox pesado. **Importante para automação:**
  quando o stdin não é um terminal interativo (pipes, CI, cron), o script não faz a
  pergunta `[s/N]` — ele **aborta** com erro diante de letterbox pesado, a menos que
  `--force` esteja presente.
- `--no-validate`: pula a autoverificação pós-codificação, se você já validar por fora.

Detalhes de comportamento que valem saber ao automatizar:

- O aviso de letterbox dispara quando o conteúdo útil cobriria menos de **70%** do
  quadro 480×640 após o scale-to-fit (constante `MIN_FRAME_COVERAGE = 0.70` no script).
- A duração do `.wav` final é sempre um múltiplo inteiro da duração do chunk
  (arredondada para cima): um vídeo de 7,5s vira ~8s de blocos, com o último chunk
  parcialmente preenchido. A conciliação com a duração exata do reel fica a cargo do
  software de masterização do DCP.
- Metadados de rotação (vídeos de celular gravados em pé mas armazenados "deitados"
  com tag de rotação 90/270) são detectados via ffprobe e considerados no cálculo de
  proporção/letterbox.
