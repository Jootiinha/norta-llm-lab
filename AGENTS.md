# AGENTS.md

Orientacoes para agentes que forem trabalhar neste repositorio.

## Visao geral

Este projeto e um laboratorio local para testar modelos de linguagem com `transformers`, rodar inferencia simples e monitorar recursos de CPU/GPU.

O codigo Python fica diretamente em `src/` e deve ser executado pelos caminhos dos arquivos.

## Estrutura

```text
.
├── models/                 # modelos locais; nao versionar pesos
├── scripts/                # scripts de conveniencia
│   ├── setup.sh            # configura venv e instala dependencias
│   └── run.sh              # inferencia padrao
├── src/                    # codigo Python do projeto
│   ├── run_model.py        # inferencia local
│   └── utils/monitor.py    # monitor de recursos
├── Makefile                # atalhos de execucao
├── pyproject.toml          # dependencias do Poetry
├── poetry.lock             # lockfile do Poetry
└── README.md               # documentacao para usuarios
```

## Comandos uteis

Instalar dependencias:

```bash
make setup
```

O alvo `setup` executa `scripts/setup.sh`, configura `.venv` local via Poetry e instala as dependencias.

Rodar inferencia padrao:

```bash
make run
```

Rodar inferencia com monitor vinculado ao PID:

```bash
make run-monitor
```

Esse fluxo mostra o monitor no topo, as ultimas linhas do console abaixo em tempo quase real e salva a saida completa em `logs/run-monitor-*.log`.

Rodar monitor:

```bash
make monitor
```

Rodar monitor uma vez, util para validacao rapida:

```bash
make monitor ARGS="--once"
```

Executar inferencia manualmente:

```bash
poetry run python -B src/run_model.py \
  --model models/qwen3-0.6b \
  --prompt "Explique em portugues brasileiro o que e RAG em LLMs."
```

Limpar caches Python:

```bash
make clean
```

## Regras de manutencao

- Nao versione modelos, pesos, checkpoints ou caches do Hugging Face.
- Mantenha arquivos grandes dentro de `models/`, que e ignorado pelo Git.
- Preserve `models/.gitkeep` para manter a pasta no repositorio.
- Prefira comandos via `Makefile` quando existirem.
- Ao criar entradas principais em Python, coloque-as em `src/`.
- Ao criar utilitarios Python, coloque-os em `src/utils/`.
- Ao criar scripts auxiliares de shell, coloque-os em `scripts/`.
- Atualize o `README.md` quando mudar comandos, estrutura ou fluxo de uso.
- Evite mudar os nomes dos diretorios de modelos sem atualizar o `Makefile`, os scripts em `scripts/` e o README.

## Validacao antes de finalizar

Para mudancas que nao carregam modelos, rode pelo menos:

```bash
make monitor ARGS="--once"
```

Para mudancas em inferencia, valide com um modelo local pequeno quando disponivel:

```bash
make run
```

Se a validacao de inferencia nao for executada por custo de memoria, tempo ou ausencia do modelo local, registre isso na resposta final.

## Observacoes sobre modelos

Os comandos de download estao documentados no `README.md`. Modelos gated podem exigir aceite dos termos no Hugging Face e login com:

```bash
poetry run huggingface-cli login
```
