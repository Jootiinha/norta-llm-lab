import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


GPU_RETRY_SECONDS = 30.0
_GPU_RETRY_AFTER = 0.0


@dataclass
class CpuSnapshot:
    total: int
    idle: int


@dataclass
class Metrics:
    cpu_percent: float
    mem_percent: float
    mem_used_gb: float
    mem_total_gb: float
    cpu_temp_c: float | None
    gpu_name: str | None
    gpu_percent: float | None
    gpu_temp_c: float | None
    gpu_mem_percent: float | None
    gpu_mem_used_mb: float | None
    gpu_mem_total_mb: float | None
    pid_cpu_percent: float | None
    pid_mem_mb: float | None
    samples_per_second: float


@dataclass
class RunningStat:
    count: int = 0
    total: float = 0.0
    min_value: float | None = None
    max_value: float | None = None
    last_value: float | None = None

    def update(self, value: float | None) -> None:
        if value is None:
            return
        self.count += 1
        self.total += value
        self.last_value = value
        self.min_value = value if self.min_value is None else min(self.min_value, value)
        self.max_value = value if self.max_value is None else max(self.max_value, value)

    @property
    def avg_value(self) -> float | None:
        if self.count == 0:
            return None
        return self.total / self.count

    def to_dict(self) -> dict[str, float | int | None]:
        return {
            "count": self.count,
            "current": self.last_value,
            "min": self.min_value,
            "max": self.max_value,
            "avg": self.avg_value,
        }


class RunStats:
    def __init__(self, run_id: str | None) -> None:
        self.run_id = run_id
        self.started_at = datetime.now(timezone.utc)
        self.samples = 0
        self.fields = {
            "cpu_percent": RunningStat(),
            "mem_percent": RunningStat(),
            "mem_used_gb": RunningStat(),
            "cpu_temp_c": RunningStat(),
            "gpu_percent": RunningStat(),
            "gpu_temp_c": RunningStat(),
            "gpu_mem_percent": RunningStat(),
            "gpu_mem_used_mb": RunningStat(),
            "pid_cpu_percent": RunningStat(),
            "pid_mem_mb": RunningStat(),
        }

    def update(self, metrics: Metrics) -> None:
        self.samples += 1
        for name, stat in self.fields.items():
            stat.update(getattr(metrics, name))

    def to_dict(self, ended_at: datetime | None = None) -> dict[str, object]:
        now = ended_at or datetime.now(timezone.utc)
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": ended_at.isoformat() if ended_at else None,
            "duration_seconds": round((now - self.started_at).total_seconds(), 3),
            "samples": self.samples,
            "metrics": {name: stat.to_dict() for name, stat in self.fields.items()},
        }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_cpu_snapshot() -> CpuSnapshot:
    values = Path("/proc/stat").read_text().splitlines()[0].split()[1:]
    nums = [int(value) for value in values]
    idle = nums[3] + nums[4]
    return CpuSnapshot(total=sum(nums), idle=idle)


def cpu_percent(previous: CpuSnapshot, current: CpuSnapshot) -> float:
    total_delta = current.total - previous.total
    idle_delta = current.idle - previous.idle
    if total_delta <= 0:
        return 0.0
    return max(0.0, min(100.0, 100.0 * (1.0 - idle_delta / total_delta)))


def read_memory() -> tuple[float, float, float]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, raw_value = line.split(":", 1)
        values[key] = int(raw_value.strip().split()[0])

    total_kb = values["MemTotal"]
    available_kb = values.get("MemAvailable", values.get("MemFree", 0))
    used_kb = total_kb - available_kb
    percent = 100.0 * used_kb / total_kb
    return percent, used_kb / 1024 / 1024, total_kb / 1024 / 1024


def read_cpu_temp() -> float | None:
    candidates: list[Path] = []
    candidates.extend(Path("/sys/class/thermal").glob("thermal_zone*/temp"))
    candidates.extend(Path("/sys/class/hwmon").glob("hwmon*/temp*_input"))

    temps: list[float] = []
    for path in candidates:
        try:
            raw = path.read_text().strip()
            value = float(raw)
            if value > 1000:
                value /= 1000
            if 0 < value < 130:
                temps.append(value)
        except (OSError, ValueError):
            continue

    return max(temps) if temps else None


def read_gpu() -> tuple[str, float, float, float, float, float] | None:
    global _GPU_RETRY_AFTER

    now = time.monotonic()
    if now < _GPU_RETRY_AFTER:
        return None

    query = (
        "--query-gpu=name,utilization.gpu,temperature.gpu,"
        "memory.used,memory.total"
    )
    command = [
        "nvidia-smi",
        query,
        "--format=csv,noheader,nounits",
    ]
    try:
        output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        _GPU_RETRY_AFTER = now + GPU_RETRY_SECONDS
        return None

    lines = output.strip().splitlines()
    if not lines:
        _GPU_RETRY_AFTER = now + GPU_RETRY_SECONDS
        return None

    first_gpu = lines[0].split(",")
    if len(first_gpu) < 5:
        _GPU_RETRY_AFTER = now + GPU_RETRY_SECONDS
        return None

    name = first_gpu[0].strip()
    util = float(first_gpu[1].strip())
    temp = float(first_gpu[2].strip())
    mem_used = float(first_gpu[3].strip())
    mem_total = float(first_gpu[4].strip())
    mem_percent = 100.0 * mem_used / mem_total if mem_total else 0.0
    return name, util, temp, mem_percent, mem_used, mem_total


def read_pid_metrics(pid: int | None, interval: float, previous_ticks: int | None) -> tuple[float | None, float | None, int | None]:
    if pid is None:
        return None, None, None

    stat_path = Path(f"/proc/{pid}/stat")
    status_path = Path(f"/proc/{pid}/status")
    if not stat_path.exists():
        return None, None, None

    try:
        stat = stat_path.read_text().split()
        current_ticks = int(stat[13]) + int(stat[14])
        clock_ticks = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        cpu = None
        if previous_ticks is not None and interval > 0:
            cpu = 100.0 * (current_ticks - previous_ticks) / clock_ticks / interval

        mem_mb = None
        for line in status_path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                mem_mb = int(line.split()[1]) / 1024
                break
        return cpu, mem_mb, current_ticks
    except (OSError, ValueError, IndexError):
        return None, None, None


def progress_bar(value: float, width: int = 22) -> str:
    value = max(0.0, min(100.0, value))
    filled = round(width * value / 100)
    color = color_for_percent(value)
    return f"{color}{'█' * filled}{RESET}{DIM}{'░' * (width - filled)}{RESET}"


def sparkline(values: deque[float], width: int = 36) -> str:
    ticks = "▁▂▃▄▅▆▇█"
    if not values:
        return ""
    sample = list(values)[-width:]
    return "".join(ticks[min(7, int(max(0, min(100, value)) / 100 * 7))] for value in sample)


def fmt_temp(value: float | None) -> str:
    return "--" if value is None else f"{value:.0f} C"


def fmt_percent(value: float | None) -> str:
    return "--" if value is None else f"{value:5.1f}%"


def fmt_number(value: float | None, suffix: str = "") -> str:
    return "--" if value is None else f"{value:.1f}{suffix}"


def card(title: str, value: str, detail: str, percent: float | None = None) -> str:
    bar = progress_bar(percent) if percent is not None else DIM + "░" * 22 + RESET
    return (
        f"┌─ {BOLD}{title:<18}{RESET} ─────────────┐\n"
        f"│ {value:<19} {bar} │\n"
        f"│ {DIM}{detail:<44}{RESET} │\n"
        f"└──────────────────────────────────────────────┘"
    )


def read_log_tail(path: Path | None, max_lines: int) -> list[str]:
    if path is None or max_lines <= 0:
        return []
    if not path.exists():
        return [f"Aguardando log: {path}"]

    lines: deque[str] = deque(maxlen=max_lines)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as file:
            for line in file:
                lines.append(line.rstrip("\n"))
    except OSError as error:
        return [f"Nao foi possivel ler o log: {error}"]

    return list(lines) or ["Log ainda sem saida."]


def truncate_line(value: str, width: int) -> str:
    if width <= 1:
        return ""
    if len(value) <= width:
        return value
    return value[: width - 1] + "…"


def metrics_to_dict(metrics: Metrics) -> dict[str, float | str | None]:
    return {
        "cpu_percent": metrics.cpu_percent,
        "mem_percent": metrics.mem_percent,
        "mem_used_gb": metrics.mem_used_gb,
        "mem_total_gb": metrics.mem_total_gb,
        "cpu_temp_c": metrics.cpu_temp_c,
        "gpu_name": metrics.gpu_name,
        "gpu_percent": metrics.gpu_percent,
        "gpu_temp_c": metrics.gpu_temp_c,
        "gpu_mem_percent": metrics.gpu_mem_percent,
        "gpu_mem_used_mb": metrics.gpu_mem_used_mb,
        "gpu_mem_total_mb": metrics.gpu_mem_total_mb,
        "pid_cpu_percent": metrics.pid_cpu_percent,
        "pid_mem_mb": metrics.pid_mem_mb,
        "samples_per_second": metrics.samples_per_second,
    }


def append_metrics_sample(path: Path | None, run_id: str | None, metrics: Metrics, elapsed_seconds: float) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": utc_now_iso(),
        "run_id": run_id,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "metrics": metrics_to_dict(metrics),
    }
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_summary(path: Path | None, stats: RunStats, ended_at: datetime | None = None) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(stats.to_dict(ended_at), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def stat_line(label: str, stat: RunningStat, suffix: str = "") -> str:
    return (
        f"{label:<12}"
        f" atual {fmt_number(stat.last_value, suffix):>8}"
        f" min {fmt_number(stat.min_value, suffix):>8}"
        f" max {fmt_number(stat.max_value, suffix):>8}"
        f" media {fmt_number(stat.avg_value, suffix):>8}"
    )


def collect_metrics(
    previous_cpu: CpuSnapshot,
    previous_pid_ticks: int | None,
    pid: int | None,
    interval: float,
) -> tuple[Metrics, CpuSnapshot, int | None]:
    time.sleep(interval)
    current_cpu = read_cpu_snapshot()
    cpu = cpu_percent(previous_cpu, current_cpu)
    mem_percent, mem_used_gb, mem_total_gb = read_memory()
    cpu_temp = read_cpu_temp()
    gpu = read_gpu()
    pid_cpu, pid_mem, current_pid_ticks = read_pid_metrics(pid, interval, previous_pid_ticks)

    if gpu:
        gpu_name, gpu_percent, gpu_temp, gpu_mem_percent, gpu_mem_used, gpu_mem_total = gpu
    else:
        gpu_name = None
        gpu_percent = None
        gpu_temp = None
        gpu_mem_percent = None
        gpu_mem_used = None
        gpu_mem_total = None

    metrics = Metrics(
        cpu_percent=cpu,
        mem_percent=mem_percent,
        mem_used_gb=mem_used_gb,
        mem_total_gb=mem_total_gb,
        cpu_temp_c=cpu_temp,
        gpu_name=gpu_name,
        gpu_percent=gpu_percent,
        gpu_temp_c=gpu_temp,
        gpu_mem_percent=gpu_mem_percent,
        gpu_mem_used_mb=gpu_mem_used,
        gpu_mem_total_mb=gpu_mem_total,
        pid_cpu_percent=pid_cpu,
        pid_mem_mb=pid_mem,
        samples_per_second=1 / interval if interval > 0 else 0,
    )
    return metrics, current_cpu, current_pid_ticks


def render(
    metrics: Metrics,
    history: dict[str, deque[float]],
    pid: int | None,
    stats: RunStats,
    log_file: Path | None = None,
    log_lines: int = 0,
) -> str:
    width = min(shutil.get_terminal_size((100, 32)).columns, 120)
    line = "─" * width
    gpu_title = metrics.gpu_name or "GPU nao detectada"

    cards = [
        card("CPU", fmt_percent(metrics.cpu_percent), f"Temp: {fmt_temp(metrics.cpu_temp_c)}", metrics.cpu_percent),
        card(
            "Memoria",
            fmt_percent(metrics.mem_percent),
            f"{metrics.mem_used_gb:.1f} GB / {metrics.mem_total_gb:.1f} GB",
            metrics.mem_percent,
        ),
        card(
            "GPU",
            fmt_percent(metrics.gpu_percent),
            f"{gpu_title[:44]}",
            metrics.gpu_percent,
        ),
        card(
            "VRAM",
            fmt_percent(metrics.gpu_mem_percent),
            "--" if metrics.gpu_mem_used_mb is None else f"{metrics.gpu_mem_used_mb:.0f} MB / {metrics.gpu_mem_total_mb:.0f} MB | Temp: {fmt_temp(metrics.gpu_temp_c)}",
            metrics.gpu_mem_percent,
        ),
    ]

    pid_label = "sem PID"
    if pid is not None and metrics.pid_cpu_percent is not None:
        pid_label = f"PID {pid}: CPU {metrics.pid_cpu_percent:.1f}% | RAM {metrics.pid_mem_mb:.0f} MB"
    elif pid is not None:
        pid_label = f"PID {pid}: nao encontrado ou aguardando amostra"

    dashboard = "\n".join(
        [
            CLEAR,
            f"{BOLD}{CYAN}LLM Training Monitor{RESET} {DIM}Ctrl+C para sair | {metrics.samples_per_second:.2f} amostras/s | {pid_label}{RESET}",
            line,
            cards[0],
            cards[1],
            cards[2],
            cards[3],
            line,
            f"{BOLD}{BLUE}Graficos{RESET}",
            f"CPU  {sparkline(history['cpu'])} {metrics.cpu_percent:5.1f}%",
            f"RAM  {sparkline(history['mem'])} {metrics.mem_percent:5.1f}%",
            f"GPU  {sparkline(history['gpu'])} {fmt_percent(metrics.gpu_percent)}",
            f"VRAM {sparkline(history['vram'])} {fmt_percent(metrics.gpu_mem_percent)}",
            line,
            f"{BOLD}{BLUE}Resumo da execucao{RESET} {DIM}{stats.run_id or 'sem run_id'} | {stats.samples} amostras{RESET}",
            stat_line("CPU %", stats.fields["cpu_percent"], "%"),
            stat_line("RAM %", stats.fields["mem_percent"], "%"),
            stat_line("RAM GB", stats.fields["mem_used_gb"], " GB"),
            stat_line("GPU %", stats.fields["gpu_percent"], "%"),
            stat_line("VRAM %", stats.fields["gpu_mem_percent"], "%"),
            stat_line("Proc CPU %", stats.fields["pid_cpu_percent"], "%"),
            stat_line("Proc RAM MB", stats.fields["pid_mem_mb"], " MB"),
        ]
    )

    if log_file is None:
        return dashboard + "\n"

    log_tail = read_log_tail(log_file, log_lines)
    console_lines = [
        line,
        f"{BOLD}{BLUE}Console{RESET} {DIM}{log_file}{RESET}",
    ]
    console_lines.extend(truncate_line(value, width) for value in log_tail)
    return dashboard + "\n" + "\n".join(console_lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor de CPU, GPU, temperatura e memoria para estudos com IA/LLMs.")
    parser.add_argument("--interval", type=float, default=1.0, help="Intervalo de atualizacao em segundos.")
    parser.add_argument("--pid", type=int, default=None, help="PID do treino ou inferencia para acompanhar CPU/RAM do processo.")
    parser.add_argument("--once", action="store_true", help="Coleta uma amostra e encerra.")
    parser.add_argument("--exit-when-pid-exits", action="store_true", help="Encerra quando o PID informado nao existir mais.")
    parser.add_argument("--log-file", type=Path, default=None, help="Arquivo de log para exibir abaixo do monitor.")
    parser.add_argument("--log-lines", type=int, default=12, help="Quantidade de linhas do log exibidas no console.")
    parser.add_argument("--run-id", default=None, help="Identificador da execucao monitorada.")
    parser.add_argument("--metrics-file", type=Path, default=None, help="Arquivo JSONL para salvar amostras de metricas.")
    parser.add_argument("--summary-file", type=Path, default=None, help="Arquivo JSON para salvar resumo da execucao.")
    args = parser.parse_args()

    history = {
        "cpu": deque(maxlen=60),
        "mem": deque(maxlen=60),
        "gpu": deque(maxlen=60),
        "vram": deque(maxlen=60),
    }

    previous_cpu = read_cpu_snapshot()
    previous_pid_ticks = None
    stats = RunStats(args.run_id)
    started_monotonic = time.monotonic()

    print(HIDE_CURSOR, end="")
    try:
        while True:
            metrics, previous_cpu, previous_pid_ticks = collect_metrics(
                previous_cpu,
                previous_pid_ticks,
                args.pid,
                max(0.2, args.interval),
            )
            history["cpu"].append(metrics.cpu_percent)
            history["mem"].append(metrics.mem_percent)
            history["gpu"].append(metrics.gpu_percent or 0.0)
            history["vram"].append(metrics.gpu_mem_percent or 0.0)
            stats.update(metrics)
            append_metrics_sample(
                args.metrics_file,
                args.run_id,
                metrics,
                time.monotonic() - started_monotonic,
            )
            write_summary(args.summary_file, stats)

            print(render(metrics, history, args.pid, stats, args.log_file, args.log_lines), end="", flush=True)
            if args.once:
                break
            if args.exit_when_pid_exits and args.pid is not None and not Path(f"/proc/{args.pid}").exists():
                break
    except KeyboardInterrupt:
        pass
    finally:
        write_summary(args.summary_file, stats, datetime.now(timezone.utc))
        print(SHOW_CURSOR)


if __name__ == "__main__":
    main()
