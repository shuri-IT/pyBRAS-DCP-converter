# pyBRAS-DCP-converter
Este programa transforma um vídeo em um arquivo de áudio especial (wav) que pode ser usado no Canal 15 de um DCP.


# Guia Fácil: Conversor de Vídeo para o Canal 15 (Vídeo em Língua de Sinais)



Este programa transforma um vídeo em um arquivo de áudio especial (wav) que pode ser usado no Canal 15 de um DCP.

## Requisitos



* Computador (Windows ou Mac).


* O arquivo do programa: `encode slv wav.py`.


* O vídeo para conversão (formatos comuns como .mp4 ou .mov).


* Python.


* FFmpeg.



## Instalação



### Windows



1. Acesse [https://www.python.org/downloads/](https://www.python.org/downloads/) e instale o Python.


2. Marque a caixa "Add Python to PATH" na primeira tela da instalação.


3. Abra o Windows PowerShell.


4. Execute o comando: `winget install ffmpeg`.



### Mac



1. Abra o aplicativo Terminal.


2. Instale o Homebrew executando: `/bin/bash -c "\$(curl -fsSL [https://raw.githubusercontent.com/Homebrew/install/](https://raw.githubusercontent.com/Homebrew/install/)`

3. Execute: `brew install python ffmpeg`.



## Execução



1. Crie uma pasta nova e insira nela o arquivo `encode_slv_wav.py` e o vídeo.


2. Abra o terminal ou Prompt de Comando dentro dessa pasta.


3. Execute o comando de conversão substituindo o nome do arquivo pelo nome real do seu vídeo:


* Windows: `python encode_slv_wav.py video_libras.mp4`

* Mac: `python3 encode_slv_wav.py video libras.mp4`



4. Aguarde a mensagem: `Success! Wrote video_libras.wav (use this file for DCP audio channel 15)`.


5. O arquivo `.wav` pronto aparecerá na mesma pasta.



## Solução de Problemas



| Mensagem | Solução |
| --- | --- |
| 'python' não é reconhecido | Reinstale e marque a caixinha "Add Python to PATH". |
| 'ffmpeg' não é reconhecido | Feche e abra o terminal de novo. Se persistir, reinstale o FFmpeg. |
| already exists, aborting | Já existe um arquivo .wav com esse nome na pasta. Apague-o ou renomeie, e rode o comando de novo. |
| A tela fica "travada" por um tempo | É normal em vídeos longos - só esperar. |
 
