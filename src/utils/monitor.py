import argparse
import os
import shutil
import subprocess
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BLUE = "\033[34m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[2J\033[H"


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


def color_for_percent(value: float) -> str:
    if value >= 90:
        return RED
    if value >= 70:
        return YELLOW
    return GREEN


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
        return None

    first_gpu = output.strip().splitlines()[0].split(",")
    if len(first_gpu) < 5:
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
    args = parser.parse_args()

    history = {
        "cpu": deque(maxlen=60),
        "mem": deque(maxlen=60),
        "gpu": deque(maxlen=60),
        "vram": deque(maxlen=60),
    }

    previous_cpu = read_cpu_snapshot()
    previous_pid_ticks = None

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

            print(render(metrics, history, args.pid, args.log_file, args.log_lines), end="", flush=True)
            if args.once:
                break
            if args.exit_when_pid_exits and args.pid is not None and not Path(f"/proc/{args.pid}").exists():
                break
    except KeyboardInterrupt:
        pass
    finally:
        print(SHOW_CURSOR)


if __name__ == "__main__":
    main()
