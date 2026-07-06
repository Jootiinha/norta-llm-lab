# Norta LLM Lab

Laboratorio local para testar modelos de linguagem com `transformers`, acompanhar uso de CPU/GPU e manter os pesos dos modelos fora do Git.

## Requisitos

- Python 3.11 ou 3.12
- Poetry
- Git LFS, recomendado para baixar repositorios do Hugging Face
- GPU NVIDIA com `nvidia-smi`, opcional, mas recomendada para modelos maiores
- Conta/token do Hugging Face para modelos gated, quando aplicavel

## Instalacao

```bash
make setup
```

O setup configura o Poetry para criar a virtualenv em `.venv/`, seleciona Python 3.12 ou 3.11 e instala as dependencias do `pyproject.toml`.

Se for baixar modelos via `git clone`, instale e habilite o Git LFS:

```bash
git lfs install
```

Se algum modelo exigir autenticacao:

```bash
poetry run huggingface-cli login
```

## Estrutura do projeto

```text
.
├── models/                 # modelos baixados localmente, ignorados pelo Git
├── scripts/                # scripts de conveniencia
│   ├── setup.sh            # configura venv e instala dependencias
│   └── run.sh              # inferencia padrao
├── src/                    # codigo Python do laboratorio
│   ├── run_model.py        # inferencia local
│   └── utils/monitor.py    # monitor de recursos
├── Makefile                # atalhos de execucao
├── pyproject.toml          # dependencias e configuracao do Poetry
└── README.md               # documentacao do projeto
```

## Baixar modelos

Os modelos devem ficar em `models/`. Esse diretorio e ignorado pelo Git para evitar versionar arquivos grandes como `.safetensors`, checkpoints e estados de treino.

### Opcao recomendada: huggingface-cli

```bash
mkdir -p models

poetry run huggingface-cli download Qwen/Qwen3-0.6B \
  --local-dir models/qwen3-0.6b \
  --local-dir-use-symlinks False

poetry run huggingface-cli download CEIA-UFG/Gemma-3-Gaia-PT-BR-4b-it \
  --local-dir models/gemma-3-gaia-ptbr-4b-it \
  --local-dir-use-symlinks False

poetry run huggingface-cli download amadeusai/AV-FI-Qwen2.5-7B-PT-BR-Instruct \
  --local-dir models/amadeus-verbo-qwen2.5-7b-ptbr-instruct \
  --local-dir-use-symlinks False

poetry run huggingface-cli download baidu/Unlimited-OCR \
  --local-dir models/unlimited-ocr \
  --local-dir-use-symlinks False
```

### Opcao alternativa: git clone

```bash
mkdir -p models

git clone https://huggingface.co/Qwen/Qwen3-0.6B \
  models/qwen3-0.6b

git clone https://huggingface.co/CEIA-UFG/Gemma-3-Gaia-PT-BR-4b-it \
  models/gemma-3-gaia-ptbr-4b-it

git clone https://huggingface.co/amadeusai/AV-FI-Qwen2.5-7B-PT-BR-Instruct \
  models/amadeus-verbo-qwen2.5-7b-ptbr-instruct

git clone https://huggingface.co/baidu/Unlimited-OCR \
  models/unlimited-ocr
```

Links de referencia:

- https://huggingface.co/Qwen/Qwen3-0.6B
- https://huggingface.co/CEIA-UFG/Gemma-3-Gaia-PT-BR-4b-it
- https://huggingface.co/amadeusai/AV-FI-Qwen2.5-7B-PT-BR-Instruct
- https://huggingface.co/baidu/Unlimited-OCR

## Rodar inferencia

O script padrao usa `models/qwen3-0.6b`:

```bash
make run
```

Para rodar a inferencia e abrir o monitor vinculado ao PID do processo:

```bash
make run-monitor
```

O terminal mostra os dados do monitor no topo e as ultimas linhas do console abaixo, atualizadas em tempo quase real. A saida completa tambem fica salva em `logs/run-monitor-*.log`.

Para mudar a quantidade de linhas do console exibidas abaixo do monitor:

```bash
MONITOR_LOG_LINES=20 make run-monitor
```

Para escolher outro modelo ou prompt:

```bash
poetry run python -B src/run_model.py \
  --model models/gemma-3-gaia-ptbr-4b-it \
  --prompt "Explique em portugues brasileiro o que e RAG em LLMs." \
  --max-new-tokens 300
```

## Monitorar recursos

```bash
make monitor
```

Com intervalo customizado:

```bash
make monitor ARGS="--interval 0.5"
```

Para acompanhar um processo especifico:

```bash
make monitor ARGS="--pid 12345"
```

## Limpeza

Remove diretorios `__pycache__`:

```bash
make clean
```

## Observacoes

- Nao commit arquivos dentro de `models/`; baixe os modelos novamente quando preparar outro ambiente.
- Modelos grandes podem exigir bastante VRAM/RAM. Comece pelo `Qwen/Qwen3-0.6B` se quiser validar o ambiente.
- Para modelos gated, aceite os termos no Hugging Face e rode `poetry run huggingface-cli login` antes do download.
