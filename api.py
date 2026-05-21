"""
Backend FastAPI para o Sistema de Análise de Assinaturas.
Serve também o frontend React buildado (sem Vercel, sem ngrok).

Execute com:
  cd frontend && npm run build   (só na primeira vez ou quando mudar o frontend)
  .venv/Scripts/python.exe api.py
    Acesse: http://localhost:8001
"""
import os
import sys
import json
from ws_aplis.webhook_server import app as ws_app
import csv
import io
import queue
import asyncio
import threading
import subprocess
import tempfile
import zipfile
import time
import re
import signal
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv
load_dotenv()

import requests as _requests
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

IS_VERCEL = os.getenv("VERCEL") == "1"
BASE_DIR   = Path(__file__).parent
DATA_DIR   = Path("/tmp") if IS_VERCEL else BASE_DIR

SCRIPT     = BASE_DIR / "analisar_assinaturas_v3_vertexai.py"
PYTHON     = sys.executable if IS_VERCEL else (BASE_DIR / ".venv" / "Scripts" / "python.exe" if os.name == "nt" else "python3")

CONFIG_F   = DATA_DIR / "config.json"
RELATORIOS_DIR = DATA_DIR / "relatorios"
IMAGENS_DIR = Path(os.getenv("DIRETORIO_IMAGENS", str(DATA_DIR / "IMAGENS AWS")))
FATURAMENTO_FILE = BASE_DIR / "docs" / "requisicoes_faturamento.txt"


WAHA_URL = os.getenv("WAHA_URL", "http://localhost:4300").rstrip("/")
WAHA_SESSION = os.getenv("WAHA_SESSION", "TIBOT")
WAHA_API_KEY = os.getenv("WAHA_API_KEY")
TELEFONE_WAHA = os.getenv("TELEFONE_WAHA", "")

def _normalize_phone_list(raw_value: str):
    phones = []
    seen = set()
    for part in str(raw_value or "").split(","):
        phone = ''.join(ch for ch in part if ch.isdigit())
        if not phone or phone in seen:
            continue
        seen.add(phone)
        phones.append(phone)
    return phones

_TELEFONES_WAHA_TESTE_DEFAULT = ','.join(filter(None, [TELEFONE_WAHA, '556139634027']))
TELEFONES_WAHA_TESTE = _normalize_phone_list(
    os.getenv("TELEFONES_WAHA_TESTE", _TELEFONES_WAHA_TESTE_DEFAULT)
)
FATURAMENTO_EXEC_FILE = RELATORIOS_DIR / "faturamento_execucao_status.json"
FATURAMENTO_BASELINE_FILE = RELATORIOS_DIR / "faturamento_baseline.json"
FATURAMENTO_TELEFONES_FILE = RELATORIOS_DIR / "faturamento_telefones_overrides.json"
FATURAMENTO_DOC_RESET_FILE = RELATORIOS_DIR / "faturamento_documento_reset_por_requisicao.json"
FATURAMENTO_ASSINATURAS_MANUAIS_FILE = RELATORIOS_DIR / "faturamento_assinaturas_realizadas_manual.json"
GERENCIAMENTO_EXECUCOES_FILE = RELATORIOS_DIR / "gerenciamento_execucoes.json"
FATURAMENTO_BOOT_TIMEOUT_SEC = int(os.getenv("FATURAMENTO_BOOT_TIMEOUT_SEC", "90"))
FATURAMENTO_STALE_TIMEOUT_SEC = int(os.getenv("FATURAMENTO_STALE_TIMEOUT_SEC", "300"))
AUTENTIQUE_STATUS_CACHE_TTL_SEC = int(os.getenv("AUTENTIQUE_STATUS_CACHE_TTL_SEC", "90"))
AUTENTIQUE_DOCS_PAGE_CACHE_TTL_SEC = int(os.getenv("AUTENTIQUE_DOCS_PAGE_CACHE_TTL_SEC", "45"))
AUTENTIQUE_STATUS_MAX_PAGES = int(os.getenv("AUTENTIQUE_STATUS_MAX_PAGES", "80"))
AUTENTIQUE_STATUS_PAGE_LIMIT = int(os.getenv("AUTENTIQUE_STATUS_PAGE_LIMIT", "20"))

app = FastAPI(title="Assinaturas API")
app.mount("/ws_aplis", ws_app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── estado global ──────────────────────────────────────────────────────────────
_process: subprocess.Popen | None = None
_log_buffer: list[str] = []          # todos os logs da última execução
_log_queue: queue.Queue  = queue.Queue()   # itens novos para SSE
_faturamento_status_lock = threading.Lock()
_faturamento_exec_status = {
    "mode": None,
    "running": False,
    "started_at": None,
    "finished_at": None,
    "data_inicial": None,
    "data_final": None,
    "arquivo_requisicoes": None,
    "last_line": None,
    "last_update": None,
    "lines_count": 0,
    "etapa": None,
    "download_atual": 0,
    "download_total": 0,
    "ia_atual": 0,
    "ia_total": 0,
    "waha_atual": 0,
    "waha_total": 0,
    "enviados": 0,
    "current_requisicao": None,
    "current_arquivo": None,
}
_autentique_status_cache_lock = threading.Lock()
_autentique_status_cache = {
    "updated_at": None,
    "docs": [],
    "refreshing": False,
}
_autentique_docs_page_cache_lock = threading.Lock()
_autentique_docs_page_cache = {}
_faturamento_baseline_lock = threading.Lock()
_faturamento_baseline = {
    "from_ts": None,  # ISO local timestamp. Apenas dados >= esse marco aparecem como "marcados".
}
_gerenciamento_lock = threading.Lock()
_gerenciamento_execucoes = {
    "faturamento": [],
    "diario": [],
}
_run_state_lock = threading.Lock()
_run_state = {
    "mode": None,  # faturamento | diario
    "meta": {},
    "recorded": False,
}
_REQ13_RE = re.compile(r"(?<!\d)(\d{13})(?!\d)")

# ── config ─────────────────────────────────────────────────────────────────────
def _load_config() -> dict:
    if CONFIG_F.exists():
        try:
            return json.loads(CONFIG_F.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"modo_teste": False, "criar_tarefa_aplis": False}

def _save_config(cfg: dict):
    CONFIG_F.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")

def _append_whatsapp_log_row(status: str, mensagem: str, telefone_original: str, telefone_destino: str, erro: str = ""):
    try:
        RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
        arquivo = RELATORIOS_DIR / f"whatsapp_enviadas_{date.today().strftime('%Y%m%d')}.csv"
        existe = arquivo.exists()
        campos = ["DataHora", "TelefoneOriginal", "TelefoneDestino", "ModoTeste", "Status", "Mensagem", "Erro"]
        with arquivo.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=campos)
            if not existe:
                writer.writeheader()
            writer.writerow({
                "DataHora": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "TelefoneOriginal": telefone_original,
                "TelefoneDestino": telefone_destino,
                "ModoTeste": "NAO",
                "Status": status,
                "Mensagem": (mensagem or "").replace("\n", " ").strip(),
                "Erro": (erro or "").strip(),
            })
    except Exception:
        pass

def _persist_faturamento_exec_status():
    try:
        RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
        FATURAMENTO_EXEC_FILE.write_text(
            json.dumps(_faturamento_exec_status, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

def _persist_faturamento_baseline():
    try:
        RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
        FATURAMENTO_BASELINE_FILE.write_text(
            json.dumps(_faturamento_baseline, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

def _load_faturamento_baseline():
    if not FATURAMENTO_BASELINE_FILE.exists():
        return
    try:
        data = json.loads(FATURAMENTO_BASELINE_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        with _faturamento_baseline_lock:
            _faturamento_baseline.update({"from_ts": data.get("from_ts")})
    except Exception:
        pass

def _load_faturamento_exec_status():
    if not FATURAMENTO_EXEC_FILE.exists():
        return
    try:
        data = json.loads(FATURAMENTO_EXEC_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        with _faturamento_status_lock:
            _faturamento_exec_status.update(data)
    except Exception:
        pass

def _load_gerenciamento_execucoes():
    if not GERENCIAMENTO_EXECUCOES_FILE.exists():
        return
    try:
        data = json.loads(GERENCIAMENTO_EXECUCOES_FILE.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return
        with _gerenciamento_lock:
            for mode in ("faturamento", "diario"):
                rows = data.get(mode)
                if isinstance(rows, list):
                    _gerenciamento_execucoes[mode] = rows[-300:]
    except Exception:
        pass

def _persist_gerenciamento_execucoes():
    try:
        RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
        with _gerenciamento_lock:
            payload = {
                "faturamento": list(_gerenciamento_execucoes.get("faturamento") or [])[-300:],
                "diario": list(_gerenciamento_execucoes.get("diario") or [])[-300:],
            }
        GERENCIAMENTO_EXECUCOES_FILE.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass

def _set_current_run(mode: str, meta: dict | None = None):
    with _run_state_lock:
        _run_state["mode"] = mode
        _run_state["meta"] = dict(meta or {})
        _run_state["recorded"] = False

def _current_run_mode() -> str | None:
    with _run_state_lock:
        return _run_state.get("mode")

def _append_gerenciamento_record(mode: str, record: dict):
    if mode not in ("faturamento", "diario"):
        return
    with _gerenciamento_lock:
        rows = _gerenciamento_execucoes.setdefault(mode, [])
        rows.append(record)
        if len(rows) > 300:
            del rows[:len(rows) - 300]
    _persist_gerenciamento_execucoes()

def _safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return int(default)

def _parse_run_metrics_from_logs(lines: list[str]):
    total_analisado = 0
    com_assinatura = 0
    sem_assinatura = 0
    enviados = 0
    for line in lines or []:
        m = re.search(r"Total analisado:\s*(\d+)", line, re.IGNORECASE)
        if m:
            total_analisado = _safe_int(m.group(1), total_analisado)
        m = re.search(r"COM assinatura:\s*(\d+)", line, re.IGNORECASE)
        if m:
            com_assinatura = _safe_int(m.group(1), com_assinatura)
        m = re.search(r"SEM assinatura:\s*(\d+)", line, re.IGNORECASE)
        if m:
            sem_assinatura = _safe_int(m.group(1), sem_assinatura)
        if "Documento enviado! ID:" in line:
            enviados += 1
        m = re.search(r"Total de documentos enviados:\s*(\d+)", line, re.IGNORECASE)
        if m:
            enviados = _safe_int(m.group(1), enviados)
    return {
        "total_analisado": total_analisado,
        "com_assinatura": com_assinatura,
        "sem_assinatura": sem_assinatura,
        "enviados": enviados,
    }

def _classify_daily_run_status(return_code: int, lines: list[str] | None = None) -> str:
    logs = [str(line or "") for line in (lines or [])]
    if any("Nenhuma requisicao encontrada" in line for line in logs):
        return "sem_dados"
    if return_code != 0:
        return "erro"
    return "concluido"

def _extract_daily_run_detail(status: str, lines: list[str] | None = None) -> str:
    logs = [str(line or "").strip() for line in (lines or []) if str(line or "").strip()]
    if not logs:
        return ""

    if status == "sem_dados":
        for line in reversed(logs):
            if "Nenhuma requisicao encontrada" in line:
                return line

    if status == "erro":
        for line in reversed(logs):
            upper = line.upper()
            if upper.startswith("ERRO:") or "[ERRO]" in upper:
                return line

    return logs[-1]

def _build_gerenciamento_summary(mode: str, rows: list[dict]):
    today = date.today()
    yesterday = today - timedelta(days=1)

    def _as_date(ts: str | None):
        txt = str(ts or "")
        if not txt:
            return None
        try:
            return datetime.fromisoformat(txt).date()
        except Exception:
            return None

    today_rows = [r for r in rows if _as_date(r.get("started_at")) == today]
    yesterday_rows = [r for r in rows if _as_date(r.get("started_at")) == yesterday]

    lookback_start = today - timedelta(days=6)
    last7 = [r for r in rows if (_as_date(r.get("started_at")) or date.min) >= lookback_start]

    concluido_7d = [r for r in last7 if str(r.get("status") or "").lower() == "concluido"]
    taxa_conclusao = round((len(concluido_7d) / len(last7)) * 100, 1) if last7 else 0.0

    media_enviados_7d = 0.0
    if concluido_7d:
        media_enviados_7d = round(sum(_safe_int(r.get("enviados"), 0) for r in concluido_7d) / len(concluido_7d), 1)

    enviados_hoje = sum(_safe_int(r.get("enviados"), 0) for r in today_rows)
    enviados_ontem = sum(_safe_int(r.get("enviados"), 0) for r in yesterday_rows)
    variacao_hoje = enviados_hoje - enviados_ontem

    ultimo = rows[-1] if rows else {}

    return {
        "mode": mode,
        "total_execucoes": len(rows),
        "execucoes_7d": len(last7),
        "taxa_conclusao_7d": taxa_conclusao,
        "media_enviados_7d": media_enviados_7d,
        "enviados_hoje": enviados_hoje,
        "enviados_ontem": enviados_ontem,
        "variacao_hoje_vs_ontem": variacao_hoje,
        "ultimo_status": ultimo.get("status") or None,
        "ultimo_started_at": ultimo.get("started_at") or None,
        "ultimo_finished_at": ultimo.get("finished_at") or None,
        "ultimo_enviados": _safe_int(ultimo.get("enviados"), 0),
        "ultimo_total_alvo": _safe_int(ultimo.get("total_alvo"), 0),
    }

def _record_current_run_if_needed(status: str, logs: list[str] | None = None):
    with _run_state_lock:
        mode = _run_state.get("mode")
        if not mode or _run_state.get("recorded"):
            return
        meta = dict(_run_state.get("meta") or {})
        _run_state["recorded"] = True
        _run_state["mode"] = None
        _run_state["meta"] = {}

    now_iso = datetime.now().isoformat(timespec="seconds")
    if mode == "faturamento":
        with _faturamento_status_lock:
            snap = dict(_faturamento_exec_status)
        record = {
            "mode": "faturamento",
            "status": status,
            "started_at": snap.get("started_at") or meta.get("started_at") or now_iso,
            "finished_at": snap.get("finished_at") or now_iso,
            "data_inicial": snap.get("data_inicial") or meta.get("data_inicial") or "",
            "data_final": snap.get("data_final") or meta.get("data_final") or "",
            "arquivo_requisicoes": snap.get("arquivo_requisicoes") or meta.get("arquivo_requisicoes") or "",
            "total_alvo": _safe_int(snap.get("ia_total") or snap.get("download_total") or 0),
            "enviados": _safe_int(snap.get("enviados") or 0),
            "etapa_final": snap.get("etapa") or "",
            "last_line": snap.get("last_line") or "",
        }
        _append_gerenciamento_record("faturamento", record)
        return

    metrics = _parse_run_metrics_from_logs(logs or [])
    record = {
        "mode": "diario",
        "status": status,
        "started_at": meta.get("started_at") or now_iso,
        "finished_at": now_iso,
        "data_inicial": meta.get("data_inicial") or "",
        "data_final": meta.get("data_final") or "",
        "total_alvo": _safe_int(metrics.get("total_analisado") or 0),
        "com_assinatura": _safe_int(metrics.get("com_assinatura") or 0),
        "sem_assinatura": _safe_int(metrics.get("sem_assinatura") or 0),
        "enviados": _safe_int(metrics.get("enviados") or 0),
        "last_line": _extract_daily_run_detail(status, logs),
    }
    _append_gerenciamento_record("diario", record)

def _faturamento_set_running(data_inicial: str, data_final: str, arquivo_requisicoes: str):
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    with _faturamento_status_lock:
        _faturamento_exec_status.update({
            "mode": "faturamento",
            "running": True,
            "started_at": started_at,
            "finished_at": None,
            "data_inicial": data_inicial,
            "data_final": data_final,
            "arquivo_requisicoes": arquivo_requisicoes,
            "last_line": "[INFO] Execucao de faturamento iniciada.",
            "last_update": started_at,
            "lines_count": 0,
            "etapa": "init",
            "download_atual": 0,
            "download_total": 0,
            "ia_atual": 0,
            "ia_total": 0,
            "waha_atual": 0,
            "waha_total": 0,
            "enviados": 0,
            "current_requisicao": None,
            "current_arquivo": None,
        })
        _persist_faturamento_exec_status()

def _faturamento_update_from_log_line(line: str):
    with _faturamento_status_lock:
        _faturamento_exec_status["last_line"] = line
        _faturamento_exec_status["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _faturamento_exec_status["lines_count"] = int(_faturamento_exec_status.get("lines_count", 0) or 0) + 1

        if "Conectando a AWS S3" in line:
            _faturamento_exec_status["etapa"] = "download"
        elif "Analisando" in line and "guias com Inteligencia" in line:
            _faturamento_exec_status["etapa"] = "ia"
        elif "RELATORIO DE ANALISE" in line:
            _faturamento_exec_status["etapa"] = "relatorio"
        elif "Enviando mensagens de confirmacao" in line:
            _faturamento_exec_status["etapa"] = "waha"
        elif "Aguardando confirmac" in line:
            _faturamento_exec_status["etapa"] = "aguardando"
        elif "ENVIO DE DOCUMENTOS" in line:
            _faturamento_exec_status["etapa"] = "autentique"
        elif "documentos_autentique_producao" in line or "Modo apenas-log-motivos finalizado" in line:
            _faturamento_exec_status["etapa"] = "done"

        m = re.match(r"^\s*\[(\d+)/(\d+)\]\s+Conv\s+\S+\s+\|\s+Tipo\s+\S+\s+\|\s+(\S+)\s+\((.+)\)", line)
        if m:
            _faturamento_exec_status["download_atual"] = int(m.group(1))
            _faturamento_exec_status["download_total"] = int(m.group(2))
            _faturamento_exec_status["current_requisicao"] = m.group(3)
            _faturamento_exec_status["current_arquivo"] = m.group(4)

        m = re.match(r"^\s*\[(\d+)/(\d+)\]\s+Guia\s+(\S+):\s+(.+)", line)
        if m:
            _faturamento_exec_status["ia_atual"] = int(m.group(1))
            _faturamento_exec_status["ia_total"] = int(m.group(2))
            _faturamento_exec_status["current_requisicao"] = m.group(3)

        m = re.match(r"^\[(\d+)/(\d+)\]\s+Req\s+(\S+)", line)
        if m:
            _faturamento_exec_status["waha_atual"] = int(m.group(1))
            _faturamento_exec_status["waha_total"] = int(m.group(2))
            _faturamento_exec_status["current_requisicao"] = m.group(3)

        if "Documento enviado! ID:" in line:
            _faturamento_exec_status["enviados"] = int(_faturamento_exec_status.get("enviados", 0) or 0) + 1

        m = re.search(r"Total de documentos enviados:\s*(\d+)", line)
        if m:
            _faturamento_exec_status["enviados"] = int(m.group(1))

        _persist_faturamento_exec_status()

def _faturamento_set_finished():
    with _faturamento_status_lock:
        _faturamento_exec_status["running"] = False
        _faturamento_exec_status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if _faturamento_exec_status.get("etapa") not in ("done", "cancelado", "interrompido"):
            _faturamento_exec_status["etapa"] = "done"
        _persist_faturamento_exec_status()

def _faturamento_set_cancelled():
    with _faturamento_status_lock:
        _faturamento_exec_status["running"] = False
        _faturamento_exec_status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _faturamento_exec_status["etapa"] = "cancelado"
        _faturamento_exec_status["last_line"] = "[INFO] Execucao cancelada pelo usuario"
        _persist_faturamento_exec_status()

def _is_process_running() -> bool:
    return _process is not None and _process.poll() is None

def _parse_local_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None

def _seconds_since(ts: str | None) -> float | None:
    dt = _parse_local_iso(ts)
    if not dt:
        return None
    return max(0.0, (datetime.now() - dt).total_seconds())

def _faturamento_mark_interrupted(reason: str):
    with _faturamento_status_lock:
        _faturamento_exec_status["running"] = False
        _faturamento_exec_status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _faturamento_exec_status["etapa"] = "interrompido"
        _faturamento_exec_status["last_line"] = reason
        _faturamento_exec_status["last_update"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        _persist_faturamento_exec_status()

def _reconcile_faturamento_exec_status():
    """Evita estado fantasma: snapshot running=true sem processo real ativo."""
    proc_running = _is_process_running()
    with _faturamento_status_lock:
        snap_running = bool(_faturamento_exec_status.get("running"))
        lines_count = int(_faturamento_exec_status.get("lines_count") or 0)
        started_at = _faturamento_exec_status.get("started_at")
        last_update = _faturamento_exec_status.get("last_update")

    if not snap_running:
        return

    if not proc_running:
        with _faturamento_status_lock:
            if not _faturamento_exec_status.get("running"):
                return
            _faturamento_exec_status["running"] = False
            _faturamento_exec_status["finished_at"] = _faturamento_exec_status.get("finished_at") or time.strftime("%Y-%m-%dT%H:%M:%S")
            etapa_atual = _faturamento_exec_status.get("etapa")
            if etapa_atual not in ("done", "cancelado"):
                _faturamento_exec_status["etapa"] = "interrompido"
            if not (_faturamento_exec_status.get("last_line") or "").strip():
                _faturamento_exec_status["last_line"] = "[INFO] Execucao encerrada sem atividade recente."
            _persist_faturamento_exec_status()
        return

    # Processo ativo sem qualquer log por muito tempo: encerra para evitar loop infinito.
    sem_logs_ha = _seconds_since(started_at)
    if lines_count == 0 and sem_logs_ha is not None and sem_logs_ha >= max(30, FATURAMENTO_BOOT_TIMEOUT_SEC):
        proc = _process
        if proc and proc.poll() is None:
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        _faturamento_mark_interrupted("[ERRO] Execucao travada no inicio (sem logs). Processo interrompido automaticamente.")
        return

    # Processo ativo com logs antigos e sem progresso: encerra por watchdog.
    inativo_ha = _seconds_since(last_update)
    if lines_count > 0 and inativo_ha is not None and inativo_ha >= max(60, FATURAMENTO_STALE_TIMEOUT_SEC):
        proc = _process
        if proc and proc.poll() is None:
            _terminate_process_tree(proc)
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        _faturamento_mark_interrupted("[ERRO] Execucao sem progresso por muito tempo. Processo interrompido automaticamente.")
        return

def _terminate_process_tree(proc: subprocess.Popen):
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=10,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        try:
            proc.terminate()
        except Exception:
            pass

def _iter_recent_whatsapp_rows(max_rows: int = 8000):
    if not RELATORIOS_DIR.exists():
        return []
    files = sorted(RELATORIOS_DIR.glob("whatsapp_enviadas_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    rows = []
    for path in files:
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                rows.extend(list(csv.DictReader(f)))
        except Exception:
            continue
        if len(rows) >= max_rows:
            break
    return rows[-max_rows:]

# ── modelos ────────────────────────────────────────────────────────────────────
class ConfigIn(BaseModel):
    modo_teste: bool | None = None
    criar_tarefa_aplis: bool | None = None

class RunIn(BaseModel):
    data: date | None = None
    data_inicial: date | None = None
    data_final: date | None = None

class FaturamentoRunIn(BaseModel):
    data_inicial: date | None = None
    data_final: date | None = None

class FaturamentoRunIndividualIn(BaseModel):
    requisicao: str
    data_inicial: date | None = None
    data_final: date | None = None

class FaturamentoTelefoneIn(BaseModel):
    requisicao: str
    telefone: str

class FaturamentoRequisicaoIn(BaseModel):
    requisicao: str

def _load_faturamento_telefones_overrides() -> dict:
    if not FATURAMENTO_TELEFONES_FILE.exists():
        return {}
    try:
        data = json.loads(FATURAMENTO_TELEFONES_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if str(k).isdigit()}
    except Exception:
        pass
    return {}

def _save_faturamento_telefones_overrides(data: dict):
    RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
    FATURAMENTO_TELEFONES_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _load_faturamento_doc_reset_map() -> dict:
    if not FATURAMENTO_DOC_RESET_FILE.exists():
        return {}
    try:
        data = json.loads(FATURAMENTO_DOC_RESET_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if str(k).isdigit()}
    except Exception:
        pass
    return {}

def _save_faturamento_doc_reset_map(data: dict):
    RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
    FATURAMENTO_DOC_RESET_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _load_faturamento_assinaturas_manuais_map() -> dict:
    if not FATURAMENTO_ASSINATURAS_MANUAIS_FILE.exists():
        return {}
    try:
        data = json.loads(FATURAMENTO_ASSINATURAS_MANUAIS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if str(k).isdigit()}
    except Exception:
        pass
    return {}

def _save_faturamento_assinaturas_manuais_map(data: dict):
    RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
    FATURAMENTO_ASSINATURAS_MANUAIS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _normalizar_telefone_br(telefone: str) -> str:
    tel = ''.join(ch for ch in str(telefone or '') if ch.isdigit())
    if tel.startswith('00'):
        tel = tel[2:]
    if tel and not tel.startswith('55'):
        tel = f"55{tel}"
    if len(tel) not in (12, 13):
        return ""
    return tel

# ── rotas ──────────────────────────────────────────────────────────────────────
@app.get("/api/status")
def status():
    _reconcile_faturamento_exec_status()
    cfg = _load_config()
    running = _is_process_running()
    return {
        "running": running,
        "modo_teste": cfg.get("modo_teste", True),
        "criar_tarefa_aplis": cfg.get("criar_tarefa_aplis", False),
        "log_lines": len(_log_buffer),
    }

@app.post("/api/config")
def update_config(body: ConfigIn):
    cfg = _load_config()
    if body.modo_teste is not None:
        cfg["modo_teste"] = body.modo_teste
    if body.criar_tarefa_aplis is not None:
        cfg["criar_tarefa_aplis"] = body.criar_tarefa_aplis
    _save_config(cfg)
    return {
        "ok": True,
        "modo_teste": cfg.get("modo_teste", True),
        "criar_tarefa_aplis": cfg.get("criar_tarefa_aplis", False),
    }

@app.post("/api/run")
def run_analysis(body: RunIn):
    global _process, _log_buffer

    if _process and _process.poll() is None:
        return {"error": "Já está executando. Aguarde ou clique em Parar."}

    cfg = _load_config()
    if body.data_inicial and body.data_final:
        data_ini_date = body.data_inicial
        data_fim_date = body.data_final
    elif body.data:
        data_ini_date = body.data
        data_fim_date = body.data
    else:
        return {"error": "Informe data única ou período (data_inicial e data_final)."}

    if data_ini_date > data_fim_date:
        return {"error": "data_inicial não pode ser maior que data_final."}

    data_ini = data_ini_date.isoformat()
    data_fim = data_fim_date.isoformat()

    env = os.environ.copy()
    env["MODO_TESTE"] = "true" if cfg.get("modo_teste", True) else "false"
    env["CRIAR_TAREFA_APLIS"] = "true" if cfg.get("criar_tarefa_aplis", False) else "false"
    env["FATURAMENTO_PERMITIR_REENVIO"] = "true"
    env["PYTHONUNBUFFERED"] = "1"

    # Limpa estado anterior
    _log_buffer = []
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break

    _process = subprocess.Popen(
        [str(PYTHON), "-u", str(SCRIPT), "--data-inicial", data_ini, "--data-final", data_fim],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        encoding="utf-8",
        errors="replace",
    )

    _set_current_run("diario", {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "data_inicial": data_ini,
        "data_final": data_fim,
    })

    def _reader():
        try:
            for line in _process.stdout:
                stripped = line.rstrip()
                _log_buffer.append(stripped)
                _log_queue.put(stripped)
            
            return_code = _process.wait()
            status = _classify_daily_run_status(return_code, list(_log_buffer))
            if return_code != 0:
                err_msg = f"ERRO: O processo diário terminou com código {return_code}"
                _log_buffer.append(err_msg)
                _log_queue.put(err_msg)
            _record_current_run_if_needed(status, logs=list(_log_buffer))
        except Exception as e:
            err_msg = f"ERRO na thread de log diário: {str(e)}"
            _log_buffer.append(err_msg)
            _log_queue.put(err_msg)
            _record_current_run_if_needed("erro", logs=list(_log_buffer))
        finally:
            _log_queue.put("__DONE__")

    threading.Thread(target=_reader, daemon=True).start()
    return {"ok": True, "data_inicial": data_ini, "data_final": data_fim}

@app.post("/api/stop")
def stop_analysis():
    global _process
    if _process and _process.poll() is None:
        mode = _current_run_mode()
        _terminate_process_tree(_process)
        try:
            _process.wait(timeout=5)
        except Exception:
            try:
                _process.kill()
            except Exception:
                pass
        if mode == "faturamento":
            _faturamento_set_cancelled()
        _record_current_run_if_needed("cancelado", logs=list(_log_buffer))
        _log_queue.put("__DONE__")
        return {"ok": True}
    return {"error": "Nenhum processo em execução"}

@app.post("/api/faturamento/run")
def run_faturamento(body: FaturamentoRunIn):
    """Executa envio separado somente para requisições da lista de faturamento."""
    global _process, _log_buffer

    if _process and _process.poll() is None:
        return {"error": "Já está executando. Aguarde ou clique em Parar."}

    if body.data_inicial and body.data_final and body.data_inicial > body.data_final:
        return {"error": "data_inicial não pode ser maior que data_final."}

    if not FATURAMENTO_FILE.exists():
        return {"error": f"Arquivo de faturamento não encontrado: {FATURAMENTO_FILE}"}

    cfg = _load_config()
    data_ini = body.data_inicial.isoformat() if body.data_inicial else ""
    data_fim = body.data_final.isoformat() if body.data_final else ""

    env = os.environ.copy()
    env["MODO_TESTE"] = "true" if cfg.get("modo_teste", True) else "false"
    env["CRIAR_TAREFA_APLIS"] = "true" if cfg.get("criar_tarefa_aplis", False) else "false"
    env["FATURAMENTO_PERMITIR_REENVIO"] = "true"
    env["PYTHONUNBUFFERED"] = "1"

    _log_buffer = []
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break

    _process = subprocess.Popen(
        [
            str(PYTHON), "-u", str(SCRIPT),
            "--somente-requisicoes-arquivo", str(FATURAMENTO_FILE),
            "--ignorar-periodo-quando-lista",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        encoding="utf-8",
        errors="replace",
    )

    _faturamento_set_running(
        data_inicial=data_ini,
        data_final=data_fim,
        arquivo_requisicoes=FATURAMENTO_FILE.name,
    )
    _set_current_run("faturamento", {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "data_inicial": data_ini,
        "data_final": data_fim,
        "arquivo_requisicoes": FATURAMENTO_FILE.name,
    })

    def _reader():
        try:
            for line in _process.stdout:
                stripped = line.rstrip()
                _log_buffer.append(stripped)
                _log_queue.put(stripped)
                _faturamento_update_from_log_line(stripped)
            
            return_code = _process.wait()
            if return_code != 0:
                err_msg = f"ERRO: O processo faturamento terminou com código {return_code}"
                _log_buffer.append(err_msg)
                _log_queue.put(err_msg)
                _faturamento_set_finished()
                _record_current_run_if_needed("erro", logs=list(_log_buffer))
            else:
                _faturamento_set_finished()
                _record_current_run_if_needed("concluido")
        except Exception as e:
            err_msg = f"ERRO na thread de log faturamento: {str(e)}"
            _log_buffer.append(err_msg)
            _log_queue.put(err_msg)
            _faturamento_set_finished()
            _record_current_run_if_needed("erro", logs=list(_log_buffer))
        finally:
            _log_queue.put("__DONE__")

    threading.Thread(target=_reader, daemon=True).start()
    return {
        "ok": True,
        "modo": "faturamento",
        "data_inicial": data_ini,
        "data_final": data_fim,
        "periodo_ignorado": True,
        "arquivo_requisicoes": FATURAMENTO_FILE.name,
    }

@app.post("/api/faturamento/run-individual")
def run_faturamento_individual(body: FaturamentoRunIndividualIn):
    """Executa envio separado para uma única requisição no painel de faturamento."""
    global _process, _log_buffer

    if _process and _process.poll() is None:
        return {"error": "Já está executando. Aguarde ou clique em Parar."}

    req = _normalizar_req(body.requisicao)
    if len(req) != 13:
        return {"error": "Requisição inválida. Informe os 13 dígitos."}

    if body.data_inicial and body.data_final and body.data_inicial > body.data_final:
        return {"error": "data_inicial não pode ser maior que data_final."}

    watch = _load_faturamento_requisicoes()
    if watch and req not in {w.get("requisicao") for w in watch}:
        return {"error": "Requisição não encontrada na lista de faturamento."}

    cfg = _load_config()
    data_ini = body.data_inicial.isoformat() if body.data_inicial else ""
    data_fim = body.data_final.isoformat() if body.data_final else ""

    env = os.environ.copy()
    env["MODO_TESTE"] = "true" if cfg.get("modo_teste", True) else "false"
    env["CRIAR_TAREFA_APLIS"] = "true" if cfg.get("criar_tarefa_aplis", False) else "false"
    env["FATURAMENTO_PERMITIR_REENVIO"] = "true"
    env["PYTHONUNBUFFERED"] = "1"

    telefones_override = _load_faturamento_telefones_overrides()
    force_reenvio_por_telefone = bool(telefones_override.get(req))
    if force_reenvio_por_telefone:
        env["FATURAMENTO_PERMITIR_REENVIO"] = "true"

    RELATORIOS_DIR.mkdir(parents=True, exist_ok=True)
    alvo_file = RELATORIOS_DIR / f"requisicao_faturamento_individual_{req}.txt"
    alvo_file.write_text(f"{req}\n", encoding="utf-8")

    _log_buffer = []
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except queue.Empty:
            break

    _process = subprocess.Popen(
        [
            str(PYTHON), "-u", str(SCRIPT),
            "--somente-requisicoes-arquivo", str(alvo_file),
            "--ignorar-periodo-quando-lista",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env,
        cwd=str(BASE_DIR),
        encoding="utf-8",
        errors="replace",
    )

    _faturamento_set_running(
        data_inicial=data_ini,
        data_final=data_fim,
        arquivo_requisicoes=alvo_file.name,
    )
    _set_current_run("faturamento", {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "data_inicial": data_ini,
        "data_final": data_fim,
        "arquivo_requisicoes": alvo_file.name,
    })

    def _reader():
        try:
            for line in _process.stdout:
                stripped = line.rstrip()
                _log_buffer.append(stripped)
                _log_queue.put(stripped)
                _faturamento_update_from_log_line(stripped)
            
            return_code = _process.wait()
            if return_code != 0:
                err_msg = f"ERRO: O processo individual terminou com código {return_code}"
                _log_buffer.append(err_msg)
                _log_queue.put(err_msg)
                _faturamento_set_finished()
                _record_current_run_if_needed("erro", logs=list(_log_buffer))
            else:
                _faturamento_set_finished()
                _record_current_run_if_needed("concluido")
        except Exception as e:
            err_msg = f"ERRO na thread de log individual: {str(e)}"
            _log_buffer.append(err_msg)
            _log_queue.put(err_msg)
            _faturamento_set_finished()
            _record_current_run_if_needed("erro", logs=list(_log_buffer))
        finally:
            _log_queue.put("__DONE__")

    threading.Thread(target=_reader, daemon=True).start()
    return {
        "ok": True,
        "modo": "faturamento-individual",
        "requisicao": req,
        "data_inicial": data_ini,
        "data_final": data_fim,
        "periodo_ignorado": True,
        "arquivo_requisicoes": alvo_file.name,
        "force_reenvio_por_telefone": force_reenvio_por_telefone,
    }

@app.post("/api/faturamento/telefone")
def set_faturamento_telefone(body: FaturamentoTelefoneIn):
    req = _normalizar_req(body.requisicao)
    if len(req) != 13:
        return {"error": "Requisição inválida. Informe os 13 dígitos."}

    tel = _normalizar_telefone_br(body.telefone)
    overrides = _load_faturamento_telefones_overrides()
    telefone_anterior = overrides.get(req, "")

    # Telefone vazio remove override manual.
    if not str(body.telefone or '').strip():
        if req in overrides:
            del overrides[req]
            _save_faturamento_telefones_overrides(overrides)
        return {"ok": True, "requisicao": req, "telefone": "", "removed": True}

    if not tel:
        return {"error": "Telefone inválido. Informe DDD + número (com ou sem 55)."}

    overrides[req] = tel
    _save_faturamento_telefones_overrides(overrides)

    reenvio_habilitado = telefone_anterior != tel
    reset_at = None
    if reenvio_habilitado:
        reset_at = datetime.now().isoformat(timespec="seconds")
        resets = _load_faturamento_doc_reset_map()
        resets[req] = reset_at
        _save_faturamento_doc_reset_map(resets)

        assinaturas_manuais = _load_faturamento_assinaturas_manuais_map()
        if req in assinaturas_manuais:
            del assinaturas_manuais[req]
            _save_faturamento_assinaturas_manuais_map(assinaturas_manuais)

        with _autentique_status_cache_lock:
            _autentique_status_cache["updated_at"] = None
            _autentique_status_cache["docs"] = []
            _autentique_status_cache["refreshing"] = False
        with _autentique_docs_page_cache_lock:
            _autentique_docs_page_cache.clear()

    return {
        "ok": True,
        "requisicao": req,
        "telefone": tel,
        "removed": False,
        "reenvio_habilitado": reenvio_habilitado,
        "reset_at": reset_at,
    }

@app.post("/api/faturamento/requisicao/reset-status-doc")
def reset_faturamento_status_doc(body: FaturamentoRequisicaoIn):
    req = _normalizar_req(body.requisicao)
    if len(req) != 13:
        return {"error": "Requisição inválida. Informe os 13 dígitos."}

    now_iso = datetime.now().isoformat(timespec="seconds")
    resets = _load_faturamento_doc_reset_map()
    resets[req] = now_iso
    _save_faturamento_doc_reset_map(resets)

    # Limpa cache para refletir imediatamente no painel.
    with _autentique_status_cache_lock:
        _autentique_status_cache["updated_at"] = None
        _autentique_status_cache["docs"] = []
        _autentique_status_cache["refreshing"] = False
    with _autentique_docs_page_cache_lock:
        _autentique_docs_page_cache.clear()

    return {"ok": True, "requisicao": req, "reset_at": now_iso}

@app.post("/api/faturamento/requisicao/assinar-realizada")
def faturamento_assinar_realizada(body: FaturamentoRequisicaoIn):
    req = _normalizar_req(body.requisicao)
    if len(req) != 13:
        return {"error": "Requisição inválida. Informe os 13 dígitos."}

    # Nunca sobrescreve o que já está assinado; marcação manual é apenas complemento
    # para itens em outros status (ex.: enviado/visualizado/pendente/não enviado).
    itens_status, _ = _build_faturamento_status(search=req, convenio='')
    for item in itens_status or []:
        if _normalizar_req(item.get('requisicao')) == req and str(item.get('status_documento') or '').upper() == 'ASSINADO':
            return {
                "ok": True,
                "requisicao": req,
                "already_marked": True,
                "already_signed": True,
                "assinado_em": item.get('assinado_em') or '',
            }

    now_iso = datetime.now().isoformat(timespec="seconds")
    assinaturas = _load_faturamento_assinaturas_manuais_map()
    already = bool(assinaturas.get(req))
    if not already:
        assinaturas[req] = now_iso
        _save_faturamento_assinaturas_manuais_map(assinaturas)

    return {
        "ok": True,
        "requisicao": req,
        "assinado_em": assinaturas.get(req, now_iso),
        "already_marked": already,
    }

@app.post("/api/faturamento/requisicao/desfazer-assinatura-realizada")
def faturamento_desfazer_assinatura_realizada(body: FaturamentoRequisicaoIn):
    req = _normalizar_req(body.requisicao)
    if len(req) != 13:
        return {"error": "Requisição inválida. Informe os 13 dígitos."}

    assinaturas = _load_faturamento_assinaturas_manuais_map()
    existed = bool(assinaturas.get(req))
    if existed:
        del assinaturas[req]
        _save_faturamento_assinaturas_manuais_map(assinaturas)

    return {
        "ok": True,
        "requisicao": req,
        "removed": existed,
    }

@app.get("/api/dashboard/stream")
async def dashboard_stream():
    """SSE: empurra todo o status do sistema a cada 5s. Substitui polls individuais de status."""
    async def generate():
        while True:
            try:
                _reconcile_faturamento_exec_status()
                cfg = _load_config()
                with _faturamento_status_lock:
                    fat_exec = dict(_faturamento_exec_status)
                with _gerenciamento_lock:
                    fat_rows = list(_gerenciamento_execucoes.get("faturamento") or [])
                    dia_rows = list(_gerenciamento_execucoes.get("diario") or [])
                payload = {
                    "status": {
                        "running": _is_process_running(),
                        "modo_teste": cfg.get("modo_teste", False),
                        "criar_tarefa_aplis": cfg.get("criar_tarefa_aplis", False),
                        "log_lines": len(_log_buffer),
                    },
                    "faturamento_exec": fat_exec,
                    "gerenciamento_faturamento": {
                        "summary": _build_gerenciamento_summary("faturamento", fat_rows),
                        "records": list(reversed(fat_rows))[:30],
                    },
                    "gerenciamento_diario": {
                        "summary": _build_gerenciamento_summary("diario", dia_rows),
                        "records": list(reversed(dia_rows))[:30],
                    },
                }
                yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            except Exception:
                pass
            await asyncio.sleep(5)
    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@app.get("/api/logs/history")
def logs_history():
    """Retorna todos os logs já capturados (para reload de página)."""
    return {"lines": _log_buffer}

@app.get("/api/logs")
async def stream_logs(from_line: int = 0):
    """SSE: envia logs novos. from_line=N pula os N primeiros do buffer."""

    async def generate():
        # 1) manda o histórico já existente (útil se o cliente reconectar)
        for line in _log_buffer[from_line:]:
            yield f"data: {json.dumps({'line': line})}\n\n"

        # 2) stream em tempo real
        while True:
            try:
                line = _log_queue.get_nowait()
                yield f"data: {json.dumps({'line': line})}\n\n"
                if line == "__DONE__":
                    return
            except queue.Empty:
                await asyncio.sleep(0.15)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

# ── autentique ────────────────────────────────────────────────────────────────
AUTENTIQUE_URL   = "https://api.autentique.com.br/v2/graphql"
AUTENTIQUE_TOKEN = os.getenv("AUTENTIQUE_TOKEN")

_DOCS_QUERY = """
query($page: Int!, $limit: Int!) {
  documents(page: $page, limit: $limit) {
    total
    data {
      id
      name
      created_at
      signatures {
        name
        email
        action { name }
        viewed   { created_at }
        signed   { created_at }
        rejected { created_at }
        link { short_link }
      }
    }
  }
}
"""

_DELETE_DOC_MUTATIONS = [
        # Tentativas em formatos diferentes para compatibilidade com o schema GraphQL.
        ("mutation($id: ID!) { deleteDocument(id: $id) { id } }", "deleteDocument"),
        ("mutation($id: String!) { deleteDocument(id: $id) { id } }", "deleteDocument"),
        ("mutation($id: ID!) { destroyDocument(id: $id) { id } }", "destroyDocument"),
        ("mutation($id: String!) { destroyDocument(id: $id) { id } }", "destroyDocument"),
]

def _autentique_graphql_request(headers: dict, payload: dict, timeout: int = 30, retries: int = 1):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            r = _requests.post(AUTENTIQUE_URL, headers=headers, json=payload, timeout=timeout)
            if r.status_code == 429:
                if retries <= 1:
                    return {"errors": [{"message": "rate_limit_429"}]}
                wait = min(20, 2 * attempt)
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            wait = min(20, 2 * attempt)
            time.sleep(wait)
    if retries <= 1:
        return {"errors": [{"message": "graphql_request_failed"}]}
    raise RuntimeError(str(last_err) if last_err else "Falha em requisicao GraphQL")

def _normalizar_req(value: str) -> str:
    return ''.join(ch for ch in str(value or '') if ch.isdigit())

def _parse_faturamento_line(line: str):
    raw = line.strip()
    if not raw or raw.startswith('#'):
        return None

    # Formato principal esperado: Nome <TAB> Requisicao <TAB> Convenio
    if '\t' in raw:
        parts = [p.strip() for p in raw.split('\t') if p.strip()]
        if len(parts) >= 3:
            nome = parts[0]
            requisicao = _normalizar_req(parts[1])
            convenio = parts[2]
            if requisicao:
                return {
                    "nome": nome,
                    "requisicao": requisicao,
                    "convenio": convenio,
                }

    # Fallback por regex (nome ... 13digitos ... convenio)
    import re
    m = re.match(r"^(.*?)\s+(\d{13})\s+(.+)$", raw)
    if not m:
        return None
    return {
        "nome": m.group(1).strip(),
        "requisicao": _normalizar_req(m.group(2)),
        "convenio": m.group(3).strip(),
    }

def _load_faturamento_requisicoes():
    if not FATURAMENTO_FILE.exists():
        return []
    items = []
    seen = set()
    with FATURAMENTO_FILE.open('r', encoding='utf-8') as f:
        for line in f:
            row = _parse_faturamento_line(line)
            if not row:
                continue
            key = (row['requisicao'], row['nome'].upper(), row['convenio'].upper())
            if key in seen:
                continue
            seen.add(key)
            items.append(row)
    return items

def _load_whatsapp_rows(limit: int = 5000):
    if not RELATORIOS_DIR.exists():
        return []
    files = sorted(RELATORIOS_DIR.glob("whatsapp_enviadas_*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
    all_rows = []
    for path in files:
        try:
            with path.open('r', encoding='utf-8', newline='') as f:
                rows = list(csv.DictReader(f))
                all_rows.extend(rows)
        except Exception:
            continue
        if len(all_rows) >= limit:
            break
    return list(reversed(all_rows))[:limit]

def _parse_ts_flexible(ts: str | None):
    txt = str(ts or "").strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except Exception:
        return None

def _to_epoch_seconds(dt: datetime | None):
    if dt is None:
        return None
    try:
        return float(dt.timestamp())
    except Exception:
        return None

def _get_faturamento_baseline_epoch():
    with _faturamento_baseline_lock:
        ts = _faturamento_baseline.get("from_ts")
    return _to_epoch_seconds(_parse_ts_flexible(ts))

def _fetch_autentique_docs_all(max_pages: int = 80, limit: int = 20, request_retries: int = 1):
    if not AUTENTIQUE_TOKEN:
        return []
    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json",
    }
    docs = []
    total = None
    page = 1
    while page <= max_pages:
        payload = {"query": _DOCS_QUERY, "variables": {"page": page, "limit": limit}}
        body = _autentique_graphql_request(headers=headers, payload=payload, timeout=30, retries=request_retries)
        if "errors" in body:
            msg = str(body["errors"][0].get("message") or "erro graphql")
            # Algumas contas retornam "validation" quando a pagina excede o limite valido.
            if docs and "validation" in msg.lower():
                break
            if "rate_limit_429" in msg.lower() or "graphql_request_failed" in msg.lower():
                break
            raise RuntimeError(msg)
        block = body["data"]["documents"]
        total = block["total"] if total is None else total
        data = block["data"]
        docs.extend(data)
        if not data or len(docs) >= total:
            break
        page += 1
    return docs

def _delete_autentique_document(doc_id: str):
    if not AUTENTIQUE_TOKEN:
        return False, "AUTENTIQUE_TOKEN nao configurado"

    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json",
    }

    last_error = "Falha ao excluir documento"
    for mutation, data_key in _DELETE_DOC_MUTATIONS:
        try:
            payload = {"query": mutation, "variables": {"id": doc_id}}
            body = _autentique_graphql_request(headers=headers, payload=payload, timeout=30, retries=4)
            if body.get("errors"):
                msgs = "; ".join(str(e.get("message") or e) for e in body.get("errors") or [])
                last_error = msgs or "Erro GraphQL"
                continue

            data = body.get("data") or {}
            deleted = data.get(data_key)
            if deleted:
                return True, "ok"
        except Exception as e:
            last_error = str(e)

    # Fallback REST (quando disponível na conta/plano/api version)
    try:
        r = _requests.delete(f"https://api.autentique.com.br/v2/documents/{doc_id}", headers={"Authorization": f"Bearer {AUTENTIQUE_TOKEN}"}, timeout=30)
        if r.status_code in (200, 202, 204):
            return True, "ok"
        if r.text:
            last_error = f"REST HTTP {r.status_code}: {r.text[:180]}"
        else:
            last_error = f"REST HTTP {r.status_code}"
    except Exception as e:
        last_error = str(e)

    return False, last_error

def _get_autentique_docs_for_status():
    now = time.time()
    with _autentique_status_cache_lock:
        updated = _autentique_status_cache.get("updated_at") or 0
        cached_docs = _autentique_status_cache.get("docs") or []
        refreshing = bool(_autentique_status_cache.get("refreshing"))
        if cached_docs and (now - updated) <= max(20, AUTENTIQUE_STATUS_CACHE_TTL_SEC):
            return list(cached_docs)

    if not refreshing:
        _start_autentique_status_cache_refresh()

    # Nao bloqueia o endpoint: retorna cache atual (mesmo stale) e atualiza em segundo plano.
    with _autentique_status_cache_lock:
        return list(_autentique_status_cache.get("docs") or [])

def _start_autentique_status_cache_refresh():
    with _autentique_status_cache_lock:
        if _autentique_status_cache.get("refreshing"):
            return
        _autentique_status_cache["refreshing"] = True
        prev_docs = list(_autentique_status_cache.get("docs") or [])

    def _worker():
        docs = []
        try:
            docs = _fetch_autentique_docs_all(
                max_pages=max(12, AUTENTIQUE_STATUS_MAX_PAGES),
                limit=max(10, AUTENTIQUE_STATUS_PAGE_LIMIT),
                request_retries=1,
            )
        except Exception:
            docs = []

        # Evita regressao visual no painel quando a API retorna lote parcial temporario.
        should_apply = bool(docs)
        if should_apply and prev_docs:
            if len(docs) + 5 < len(prev_docs):
                should_apply = False

        with _autentique_status_cache_lock:
            if should_apply:
                _autentique_status_cache["updated_at"] = time.time()
                _autentique_status_cache["docs"] = list(docs)
            _autentique_status_cache["refreshing"] = False

    threading.Thread(target=_worker, daemon=True, name="autentique-status-refresh").start()

def _get_autentique_docs_page_cached(page: int, limit: int):
    now = time.time()
    key = f"{page}:{limit}"
    with _autentique_docs_page_cache_lock:
        slot = _autentique_docs_page_cache.get(key)
        if slot and (now - float(slot.get("updated_at") or 0.0)) <= max(10, AUTENTIQUE_DOCS_PAGE_CACHE_TTL_SEC):
            return slot.get("payload")
    return None

def _set_autentique_docs_page_cache(page: int, limit: int, payload: dict):
    key = f"{page}:{limit}"
    with _autentique_docs_page_cache_lock:
        _autentique_docs_page_cache[key] = {
            "updated_at": time.time(),
            "payload": payload,
        }

class AutentiqueDeleteByEmailIn(BaseModel):
    email: str
    executar: bool = False
    limite: int = 1000
    name_prefix: str | None = None
    data_inicial: date | None = None
    data_final: date | None = None
    detalhar_resultado: bool = False

class AutentiqueDeleteByRequisicaoIn(BaseModel):
    requisicao: str
    executar: bool = False
    limite: int = 200
    detalhar_resultado: bool = False

def _build_faturamento_status(search: str = "", convenio: str = ""):
    watch = _load_faturamento_requisicoes()
    if search:
        s = search.lower().strip()
        watch = [w for w in watch if s in w['nome'].lower() or s in w['requisicao'] or s in w['convenio'].lower()]
    if convenio:
        c = convenio.lower().strip()
        watch = [w for w in watch if c in w['convenio'].lower()]

    baseline_epoch = _get_faturamento_baseline_epoch()
    telefones_override = _load_faturamento_telefones_overrides()
    doc_reset_map = _load_faturamento_doc_reset_map()
    assinaturas_manuais_map = _load_faturamento_assinaturas_manuais_map()

    # Mapa de WhatsApp mais recente por requisição (extracao direta de requisicoes no texto)
    wa_latest = {}
    watch_reqs = {w['requisicao'] for w in watch}
    for row in _load_whatsapp_rows(limit=10000):
        if baseline_epoch is not None:
            row_epoch = _to_epoch_seconds(_parse_ts_flexible(row.get('DataHora')))
            if row_epoch is None or row_epoch < baseline_epoch:
                continue
        msg = (row.get('Mensagem') or '')
        if not msg:
            continue
        matches = _REQ13_RE.findall(msg)
        if not matches:
            continue
        for req_raw in matches:
            req = _normalizar_req(req_raw)
            if req not in watch_reqs:
                continue
            wa_latest[req] = {
                "status": row.get('Status') or '',
                "mensagem": msg,
                "data_hora": row.get('DataHora') or '',
                "telefone_destino": row.get('TelefoneDestino') or '',
            }

    # Mapa de documento da Autentique por requisicao
    doc_map = {}
    docs = _get_autentique_docs_for_status()

    for d in docs:
        if baseline_epoch is not None:
            doc_epoch = _to_epoch_seconds(_parse_ts_flexible(d.get('created_at')))
            if doc_epoch is None or doc_epoch < baseline_epoch:
                continue
        name = d.get('name') or ''
        parts = name.split('_')
        req = _normalizar_req(parts[1]) if len(parts) >= 2 else ''
        if not req:
            continue

        reset_ts = doc_reset_map.get(req)
        if reset_ts:
            reset_epoch = _to_epoch_seconds(_parse_ts_flexible(reset_ts))
            doc_epoch = _to_epoch_seconds(_parse_ts_flexible(d.get('created_at')))
            if reset_epoch is not None and doc_epoch is not None and doc_epoch <= reset_epoch:
                continue

        signers = [s for s in d.get('signatures') or [] if (s.get('action') or {}).get('name') == 'SIGN']
        signer = signers[0] if signers else {}
        signed_at = (signer.get('signed') or {}).get('created_at') if signer else None
        rejected_at = (signer.get('rejected') or {}).get('created_at') if signer else None
        viewed_at = (signer.get('viewed') or {}).get('created_at') if signer else None

        status = 'PENDENTE'
        if rejected_at:
            status = 'REJEITADO'
        elif signed_at:
            status = 'ASSINADO'
        elif viewed_at:
            status = 'VISUALIZADO'
        elif d.get('created_at'):
            status = 'ENVIADO'

        row = {
            "documento_id": d.get('id') or '',
            "status_documento": status,
            "enviado_em": d.get('created_at') or '',
            "assinado_em": signed_at or '',
            "rejeitado_em": rejected_at or '',
            "link": (signer.get('link') or {}).get('short_link') if signer else '',
        }
        # Mantém mais recente por data de criação
        prev = doc_map.get(req)
        if not prev or (row['enviado_em'] or '') > (prev['enviado_em'] or ''):
            doc_map[req] = row

    items = []

    def _motivo_nao_enviado(item_status: str, wa_status: str, wa_msg: str, telefone_override: str):
        status_doc = str(item_status or '').upper().strip()
        if status_doc != 'NAO_ENVIADO':
            return '', ''

        ws = str(wa_status or '').upper().strip()
        msg = str(wa_msg or '').strip().lower()
        tel = str(telefone_override or '').strip()

        if ws.startswith('RECEBIDA_NAO') or ws.startswith('RECEBIDA_PULAR'):
            return 'RECUSA', 'Paciente recusou envio no WhatsApp'
        if ws.startswith('ERRO'):
            return 'ERRO_WHATSAPP', 'Falha no envio/comunicacao WhatsApp'
        if '[liberacao teste - autentique]' in msg:
            return 'AGUARDANDO_LIBERACAO', 'Aguardando liberacao manual do operador'
        if ws.startswith('ENVIADA') or ws.startswith('AVISO_ASSINATURA') or 'deseja receber o link de assinatura' in msg:
            return 'FLUXO_WHATSAPP', 'WhatsApp enviado; aguardando proximo passo do fluxo'
        if tel:
            return 'REENVIO_MANUAL', 'Telefone manual cadastrado; pendente reenvio'
        return 'SEM_DISPARO', 'Nao houve disparo de envio para esta requisicao'

    def _resolve_status_documento(doc_status: str, wa_status: str, wa_msg: str):
        status = str(doc_status or '').upper().strip()
        if status != 'NAO_ENVIADO':
            return status
        ws = str(wa_status or '').upper().strip()
        msg = str(wa_msg or '').strip().lower()
        if ws.startswith('ENVIADA') or ws.startswith('AVISO_ASSINATURA') or 'deseja receber o link de assinatura' in msg or 'documento enviado com sucesso' in msg:
            return 'ENVIADO'
        return 'NAO_ENVIADO'

    for w in watch:
        req = w['requisicao']
        doc = doc_map.get(req, {})
        wa = wa_latest.get(req, {})
        assinatura_manual_em = assinaturas_manuais_map.get(req, '')
        assinatura_manual = bool(assinatura_manual_em)

        if assinatura_manual:
            doc = dict(doc)
            doc['status_documento'] = 'ASSINADO'
            if not doc.get('assinado_em'):
                doc['assinado_em'] = assinatura_manual_em
            if not doc.get('enviado_em'):
                doc['enviado_em'] = assinatura_manual_em

        display_status = _resolve_status_documento(
            doc.get('status_documento', 'NAO_ENVIADO'),
            wa.get('status', ''),
            wa.get('mensagem', ''),
        )
        doc = dict(doc)
        doc['status_documento'] = display_status

        motivo_code, motivo_texto = _motivo_nao_enviado(
            doc.get('status_documento', 'NAO_ENVIADO'),
            wa.get('status', ''),
            wa.get('mensagem', ''),
            telefones_override.get(req, ''),
        )

        items.append({
            "nome": w['nome'],
            "requisicao": req,
            "convenio": w['convenio'],
            "status_documento": doc.get('status_documento', 'NAO_ENVIADO'),
            "documento_id": doc.get('documento_id', ''),
            "enviado_em": doc.get('enviado_em', ''),
            "assinado_em": doc.get('assinado_em', ''),
            "rejeitado_em": doc.get('rejeitado_em', ''),
            "link_documento": doc.get('link', ''),
            "whatsapp_status": wa.get('status', ''),
            "whatsapp_data_hora": wa.get('data_hora', ''),
            "whatsapp_telefone": wa.get('telefone_destino', ''),
            "whatsapp_mensagem": wa.get('mensagem', ''),
            "telefone_override": telefones_override.get(req, ''),
            "assinatura_manual": assinatura_manual,
            "nao_enviado_motivo_code": motivo_code,
            "nao_enviado_motivo": motivo_texto,
        })

    def _teve_envio_whatsapp(item: dict) -> bool:
        status = str(item.get('whatsapp_status') or '').upper()
        mensagem = str(item.get('whatsapp_mensagem') or '')
        return (
            status.startswith('ENVIADA')
            or status.startswith('RECEBIDA_')
            or 'Deseja receber o link de assinatura' in mensagem
            or 'Documento Enviado com Sucesso' in mensagem
        )

    resumo = {
        "total": len(items),
        # Considera enviados de documento (Autentique) e de mensagem (WhatsApp)
        "enviados": sum(
            1 for i in items
            if i['status_documento'] in ('ENVIADO', 'VISUALIZADO', 'PENDENTE', 'ASSINADO', 'REJEITADO')
            or _teve_envio_whatsapp(i)
        ),
        "assinados": sum(1 for i in items if i['status_documento'] == 'ASSINADO'),
        "pendentes": sum(1 for i in items if i['status_documento'] in ('ENVIADO', 'VISUALIZADO', 'PENDENTE')),
        "nao_enviados": sum(1 for i in items if i['status_documento'] == 'NAO_ENVIADO'),
        "rejeitados": sum(1 for i in items if i['status_documento'] == 'REJEITADO'),
    }
    return items, resumo

def _csv_response_from_items(items, filename: str):
    out = io.StringIO()
    fields = [
        'nome', 'requisicao', 'convenio',
        'status_documento', 'documento_id', 'enviado_em', 'assinado_em', 'rejeitado_em', 'link_documento',
        'whatsapp_status', 'whatsapp_data_hora', 'whatsapp_telefone', 'whatsapp_mensagem', 'telefone_override',
        'nao_enviado_motivo_code', 'nao_enviado_motivo'
    ]
    writer = csv.DictWriter(out, fieldnames=fields, extrasaction='ignore')
    writer.writeheader()
    for item in items or []:
        safe_item = {campo: '' if item.get(campo) is None else item.get(campo, '') for campo in fields}
        writer.writerow(safe_item)
    data = out.getvalue().encode('utf-8-sig')
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.csv')
    tmp.write(data)
    tmp.close()
    return FileResponse(path=tmp.name, filename=filename, media_type='text/csv')

def _try_download_signed_doc_bytes(doc_id: str):
    if not doc_id or not AUTENTIQUE_TOKEN:
        return None
    headers = {"Authorization": f"Bearer {AUTENTIQUE_TOKEN}"}
    candidates = [
        f"https://api.autentique.com.br/v2/documents/{doc_id}/download?version=signed",
        f"https://api.autentique.com.br/v2/documents/{doc_id}/download/signed",
        f"https://api.autentique.com.br/v2/documents/{doc_id}/files/signed",
    ]
    for url in candidates:
        try:
            r = _requests.get(url, headers=headers, timeout=40)
            if r.status_code == 200 and r.content:
                ctype = (r.headers.get('content-type') or '').lower()
                if 'pdf' in ctype or len(r.content) > 1024:
                    return r.content
        except Exception:
            continue
    return None

@app.get("/api/autentique/documentos")
def listar_documentos(page: int = Query(1, ge=1), limit: int = Query(20, ge=1, le=100)):
    if not AUTENTIQUE_TOKEN:
        return {"error": "AUTENTIQUE_TOKEN nao configurado no ambiente"}

    cached = _get_autentique_docs_page_cached(page=page, limit=limit)
    if cached:
        return cached

    headers = {
        "Authorization": f"Bearer {AUTENTIQUE_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {"query": _DOCS_QUERY, "variables": {"page": page, "limit": limit}}
    try:
        body = _autentique_graphql_request(headers=headers, payload=payload, timeout=15, retries=2)
        if "errors" in body:
            return {"error": body["errors"][0]["message"]}
        docs_raw = body["data"]["documents"]
        total    = docs_raw["total"]
        docs     = []
        for d in docs_raw["data"]:
            # extrai apenas o assinante (action=SIGN)
            signers = [s for s in d["signatures"] if s.get("action") and s["action"]["name"] == "SIGN"]
            signer  = signers[0] if signers else {}
            # extrai número do nome do documento (Requisicao_XXXXXXX_Assinatura)
            parts = d["name"].split("_")
            requisicao = parts[1] if len(parts) >= 2 else d["name"]
            docs.append({
                "id":         d["id"],
                "requisicao": requisicao,
                "nome":       signer.get("name") or "—",
                "email":      signer.get("email") or "—",
                "criado_em":  d["created_at"],
                "visualizado": signer.get("viewed", {}).get("created_at") if signer.get("viewed") else None,
                "assinado":   signer.get("signed", {}).get("created_at") if signer.get("signed") else None,
                "rejeitado":  signer.get("rejected", {}).get("created_at") if signer.get("rejected") else None,
                "link":       signer.get("link", {}).get("short_link") if signer.get("link") else None,
            })
        resp = {"total": total, "page": page, "limit": limit, "docs": docs}
        _set_autentique_docs_page_cache(page=page, limit=limit, payload=resp)
        return resp
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/autentique/documentos/delete-by-email")
def autentique_delete_by_email(body: AutentiqueDeleteByEmailIn):
    email_target = (body.email or "").strip().lower()
    if not email_target:
        return {"error": "Informe um email valido"}

    limite = max(1, min(int(body.limite or 1000), 5000))
    name_prefix = (body.name_prefix or "").strip()
    data_inicial = body.data_inicial
    data_final = body.data_final

    if data_inicial and data_final and data_inicial > data_final:
        return {"error": "data_inicial nao pode ser maior que data_final"}

    try:
        docs = _fetch_autentique_docs_all(max_pages=120, limit=20, request_retries=6)
    except Exception as e:
        return {"error": f"Falha ao consultar documentos na Autentique: {e}"}

    candidatos = []
    for d in docs:
        signers = d.get("signatures") or []
        emails = [str((s or {}).get("email") or "").strip().lower() for s in signers]
        nome_doc = str(d.get("name") or "")
        por_email = email_target in emails
        por_prefixo = bool(name_prefix) and nome_doc.startswith(name_prefix)
        if por_email or por_prefixo:
            created_at = str(d.get("created_at") or "")
            created_date = None
            try:
                created_date = date.fromisoformat(created_at[:10]) if created_at else None
            except Exception:
                created_date = None

            if data_inicial and (not created_date or created_date < data_inicial):
                continue
            if data_final and (not created_date or created_date > data_final):
                continue

            candidatos.append({
                "id": d.get("id") or "",
                "name": nome_doc,
                "created_at": created_at,
                "emails": sorted({e for e in emails if e}),
            })

    candidatos = candidatos[:limite]

    if not body.executar:
        return {
            "ok": True,
            "dry_run": True,
            "email": email_target,
            "total_encontrados": len(candidatos),
            "limite": limite,
            "name_prefix": name_prefix,
            "data_inicial": data_inicial.isoformat() if data_inicial else None,
            "data_final": data_final.isoformat() if data_final else None,
            "docs": candidatos,
        }

    apagados = []
    falhas = []
    for c in candidatos:
        ok, msg = _delete_autentique_document(c["id"])
        if ok:
            apagados.append({"id": c["id"], "name": c["name"]})
        else:
            falhas.append({"id": c["id"], "name": c["name"], "erro": msg})

    resp = {
        "ok": True,
        "dry_run": False,
        "email": email_target,
        "name_prefix": name_prefix,
        "data_inicial": data_inicial.isoformat() if data_inicial else None,
        "data_final": data_final.isoformat() if data_final else None,
        "total_encontrados": len(candidatos),
        "apagados": len(apagados),
        "falhas": len(falhas),
    }
    if body.detalhar_resultado:
        resp["docs_apagados"] = apagados
        resp["docs_falha"] = falhas

    if apagados:
        with _autentique_docs_page_cache_lock:
            _autentique_docs_page_cache.clear()
        with _autentique_status_cache_lock:
            _autentique_status_cache["updated_at"] = None
            _autentique_status_cache["docs"] = []
            _autentique_status_cache["refreshing"] = False
    return resp

@app.post("/api/autentique/documentos/delete-by-requisicao")
def autentique_delete_by_requisicao(body: AutentiqueDeleteByRequisicaoIn):
    req_target = _normalizar_req(body.requisicao)
    if len(req_target) != 13:
        return {"error": "Informe uma requisicao valida com 13 digitos"}

    limite = max(1, min(int(body.limite or 200), 1000))
    try:
        docs = _fetch_autentique_docs_all(max_pages=120, limit=20, request_retries=6)
    except Exception as e:
        return {"error": f"Falha ao consultar documentos na Autentique: {e}"}

    candidatos = []
    for d in docs:
        nome_doc = str(d.get("name") or "")
        m = _REQ13_RE.search(nome_doc)
        req_doc = _normalizar_req(m.group(1) if m else "")
        if req_doc != req_target:
            continue

        signers = d.get("signatures") or []
        emails = [str((s or {}).get("email") or "").strip().lower() for s in signers]
        candidatos.append({
            "id": d.get("id") or "",
            "name": nome_doc,
            "created_at": str(d.get("created_at") or ""),
            "emails": sorted({e for e in emails if e}),
        })

    candidatos = candidatos[:limite]

    if not body.executar:
        return {
            "ok": True,
            "dry_run": True,
            "requisicao": req_target,
            "total_encontrados": len(candidatos),
            "limite": limite,
            "docs": candidatos,
        }

    apagados = []
    falhas = []
    for c in candidatos:
        ok, msg = _delete_autentique_document(c["id"])
        if ok:
            apagados.append({"id": c["id"], "name": c["name"]})
        else:
            falhas.append({"id": c["id"], "name": c["name"], "erro": msg})

    resp = {
        "ok": True,
        "dry_run": False,
        "requisicao": req_target,
        "total_encontrados": len(candidatos),
        "apagados": len(apagados),
        "falhas": len(falhas),
    }
    if body.detalhar_resultado:
        resp["docs_apagados"] = apagados
        resp["docs_falha"] = falhas

    if apagados:
        with _autentique_docs_page_cache_lock:
            _autentique_docs_page_cache.clear()
        with _autentique_status_cache_lock:
            _autentique_status_cache["updated_at"] = None
            _autentique_status_cache["docs"] = []
            _autentique_status_cache["refreshing"] = False
    return resp

def _get_latest_file(pattern: str) -> Path | None:
    if not RELATORIOS_DIR.exists():
        return None
    files = sorted(RELATORIOS_DIR.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None

@app.get("/api/requisicoes/{requisicao}/imagens")
def requisicao_imagens(requisicao: str):
    req = _normalizar_req(requisicao)
    if not req:
        return {"error": "Requisicao invalida"}
    if not IMAGENS_DIR.exists():
        return {"total": 0, "items": []}

    items = []
    for p in sorted(IMAGENS_DIR.iterdir()):
        if not p.is_file():
            continue
        nome = p.name
        nome_norm = ''.join(ch for ch in nome if ch.isdigit())
        if req not in nome_norm and req not in nome:
            continue
        items.append({
            "name": nome,
            "size": p.stat().st_size,
            "updated_at": p.stat().st_mtime,
            "url": f"/api/imagens/local/{quote(nome, safe='')}",
        })

    return {"total": len(items), "items": items}

@app.get("/api/imagens/local/{file_name}")
def imagem_local(file_name: str):
    if not IMAGENS_DIR.exists():
        return {"error": "Diretorio de imagens nao encontrado"}

    nome = Path(file_name).name
    if nome != file_name:
        return {"error": "Nome de arquivo invalido"}

    path = IMAGENS_DIR / nome
    if not path.exists() or not path.is_file():
        return {"error": "Arquivo nao encontrado"}

    suffix = path.suffix.lower()
    media = "application/octet-stream"
    if suffix in {".jpg", ".jpeg"}:
        media = "image/jpeg"
    elif suffix == ".png":
        media = "image/png"
    elif suffix == ".pdf":
        media = "application/pdf"

    return FileResponse(
        path=path,
        media_type=media,
        headers={"Content-Disposition": "inline"},
    )

@app.get("/api/exports/sem-telefone/latest")
def export_sem_telefone_latest():
    latest = _get_latest_file("requisicoes_sem_telefone_*.csv")
    if not latest:
        return {"ok": False, "error": "Nenhum arquivo de requisicoes sem telefone encontrado"}
    return {
        "ok": True,
        "file": latest.name,
        "updated_at": latest.stat().st_mtime,
    }

@app.get("/api/exports/sem-telefone/download")
def export_sem_telefone_download():
    latest = _get_latest_file("requisicoes_sem_telefone_*.csv")
    if not latest:
        return {"error": "Nenhum arquivo de requisicoes sem telefone encontrado"}
    return FileResponse(path=latest, filename=latest.name, media_type="text/csv")

@app.get("/api/whatsapp/enviadas")
def whatsapp_enviadas(limit: int = Query(200, ge=1, le=2000)):
    latest = _get_latest_file("whatsapp_enviadas_*.csv")
    if not latest:
        return {"total": 0, "items": []}

    try:
        with latest.open("r", encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
    except Exception as e:
        return {"error": f"Falha ao ler arquivo de WhatsApp: {e}"}

    rows = list(reversed(rows))[:limit]
    items = [
        {
            "data_hora": r.get("DataHora", ""),
            "telefone_original": r.get("TelefoneOriginal", ""),
            "telefone_destino": r.get("TelefoneDestino", ""),
            "modo_teste": r.get("ModoTeste", ""),
            "status": r.get("Status", ""),
            "mensagem": r.get("Mensagem", ""),
            "erro": r.get("Erro", ""),
        }
        for r in rows
    ]
    return {"total": len(items), "file": latest.name, "items": items}

@app.get("/api/whatsapp/mensagens")
def whatsapp_mensagens(limit: int = Query(200, ge=1, le=2000)):
    return whatsapp_enviadas(limit=limit)

@app.post("/webhook/LabWahaPlus")
async def webhook_labwaha_plus(request: Request):
    """Endpoint de webhook para integrações externas (ex.: WAHA via ngrok)."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    try:
        # Tenta extrair campos comuns de webhooks WAHA sem quebrar se o formato variar.
        event = str(payload.get("event") or payload.get("type") or "webhook").strip().upper()
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        text = (data.get("body") or data.get("text") or "").strip()
        chat_id = str(data.get("chatId") or data.get("from") or data.get("to") or "")
        tel = ''.join(ch for ch in chat_id if ch.isdigit())

        if text or tel:
            _append_whatsapp_log_row(
                status=f"RECEBIDA_{event}" if event else "RECEBIDA_WEBHOOK",
                mensagem=text,
                telefone_original=tel,
                telefone_destino=tel,
            )
    except Exception:
        pass

    return {"ok": True}

@app.get("/api/faturamento/execution/latest")
def faturamento_execution_latest():
    _reconcile_faturamento_exec_status()
    with _faturamento_status_lock:
        return dict(_faturamento_exec_status)

@app.post("/api/faturamento/reset-marcacoes")
def faturamento_reset_marcacoes():
    """Zera marcacoes visiveis do faturamento a partir de agora (mantem historico bruto)."""
    now_iso = datetime.now().isoformat(timespec="seconds")
    with _faturamento_baseline_lock:
        _faturamento_baseline["from_ts"] = now_iso
        _persist_faturamento_baseline()

    # Limpa cache para refletir imediatamente no painel.
    with _autentique_status_cache_lock:
        _autentique_status_cache["updated_at"] = None
        _autentique_status_cache["docs"] = []
        _autentique_status_cache["refreshing"] = False

    return {"ok": True, "baseline_from": now_iso}

# ── faturamento ───────────────────────────────────────────────────────────────
@app.get("/api/faturamento/status")
def faturamento_status(
    search: str = Query('', description='Busca por nome, requisicao ou convenio'),
    convenio: str = Query('', description='Filtro por convenio'),
    force_refresh: bool = Query(False, description='Forca atualizacao sincronizada do cache de status'),
):
    if force_refresh:
        with _autentique_status_cache_lock:
            prev_docs = list(_autentique_status_cache.get("docs") or [])

        try:
            docs = _fetch_autentique_docs_all(
                max_pages=max(12, AUTENTIQUE_STATUS_MAX_PAGES),
                limit=max(10, AUTENTIQUE_STATUS_PAGE_LIMIT),
                request_retries=2,
            )
            if docs:
                with _autentique_status_cache_lock:
                    _autentique_status_cache["updated_at"] = time.time()
                    _autentique_status_cache["docs"] = list(docs)
                    _autentique_status_cache["refreshing"] = False
            else:
                with _autentique_status_cache_lock:
                    _autentique_status_cache["updated_at"] = time.time()
                    _autentique_status_cache["docs"] = list(prev_docs)
                    _autentique_status_cache["refreshing"] = False
        except Exception:
            with _autentique_status_cache_lock:
                _autentique_status_cache["updated_at"] = time.time()
                _autentique_status_cache["docs"] = list(prev_docs)
                _autentique_status_cache["refreshing"] = False

    items, resumo = _build_faturamento_status(search=search, convenio=convenio)
    return {"resumo": resumo, "items": items}

@app.get("/api/gerenciamento/faturamento")
def gerenciamento_faturamento():
    with _gerenciamento_lock:
        rows = list(_gerenciamento_execucoes.get("faturamento") or [])
    summary = _build_gerenciamento_summary("faturamento", rows)
    return {
        "summary": summary,
        "records": list(reversed(rows))[:30],
    }

@app.get("/api/gerenciamento/diario")
def gerenciamento_diario():
    with _gerenciamento_lock:
        rows = list(_gerenciamento_execucoes.get("diario") or [])
    summary = _build_gerenciamento_summary("diario", rows)
    return {
        "summary": summary,
        "records": list(reversed(rows))[:30],
    }

@app.get("/api/faturamento/export/pendentes")
def faturamento_export_pendentes(
    search: str = Query(''),
    convenio: str = Query(''),
):
    items, _ = _build_faturamento_status(search=search, convenio=convenio)
    pend = [i for i in items if i['status_documento'] in ('ENVIADO', 'VISUALIZADO', 'PENDENTE')]
    return _csv_response_from_items(pend, 'faturamento_pendentes.csv')

@app.get("/api/faturamento/export/assinados")
def faturamento_export_assinados(
    search: str = Query(''),
    convenio: str = Query(''),
):
    items, _ = _build_faturamento_status(search=search, convenio=convenio)
    signed = [i for i in items if i['status_documento'] == 'ASSINADO']
    return _csv_response_from_items(signed, 'faturamento_assinados.csv')

@app.get("/api/faturamento/download/assinados")
def faturamento_download_assinados(
    search: str = Query(''),
    convenio: str = Query(''),
):
    items, _ = _build_faturamento_status(search=search, convenio=convenio)
    signed = [i for i in items if i['status_documento'] == 'ASSINADO' and i.get('documento_id')]
    if not signed:
        return {"error": "Nenhum documento assinado encontrado para baixar"}

    zip_tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
    ok_count = 0
    with zipfile.ZipFile(zip_tmp.name, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for i in signed:
            data = _try_download_signed_doc_bytes(i.get('documento_id'))
            if not data:
                continue
            safe_req = i['requisicao']
            safe_nome = ''.join(ch if ch.isalnum() or ch in (' ', '_', '-') else '_' for ch in i['nome']).strip().replace(' ', '_')
            zf.writestr(f"{safe_req}_{safe_nome}.pdf", data)
            ok_count += 1

    if ok_count == 0:
        return {"error": "Nao foi possivel baixar os PDFs assinados da Autentique com os dados disponiveis"}

    return FileResponse(path=zip_tmp.name, filename='faturamento_assinados.zip', media_type='application/zip')

# ── APLIS: debug ───────────────────────────────────────────────────────────────

@app.get("/api/aplis/debug/{cod}")
def aplis_debug(cod: str):
    """Debug: retorna o raw `requisicaoStatus` pra vermos a estrutura dos dados."""
    from ws_aplis.aplis_client import AplisClient
    client = AplisClient()
    resultado = client._post("requisicaoStatus", {"codRequisicao": cod})
    return resultado

# ── APLIS: anexar guia assinada direto (sem depender do sub-app ws_aplis) ───────
@app.post("/api/aplis/anexar/{cod_requisicao}")
def aplis_anexar_guia(cod_requisicao: str):
    """
    Fluxo completo: busca documento no Autentique → baixa PDF → anexa no APLIS.
    Criado especificamente para funcionar no Vercel sem depender de DB local.
    """
    import base64 as _b64
    from ws_aplis.config_ws import (
        APLIS_API_URL, APLIS_USER, APLIS_PASS, APLIS_ID_LABORATORIO, APLIS_TIPO_IMAGEM_GUIA
    )
    from ws_aplis.autentique_client import buscar_documentos_por_nome, buscar_documento, baixar_pdf_assinado
    from ws_aplis.aplis_client import AplisClient

    cod = ''.join(ch for ch in str(cod_requisicao or '') if ch.isdigit())
    if len(cod) != 13:
        return {"sucesso": False, "erro": f"Código inválido: '{cod_requisicao}'"}

    def _ja_possui_guia_assinada_db(cod_requisicao: str):
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "3306")),
                user=os.getenv("DB_USER", "root"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
            )
            cur = conn.cursor(dictionary=True)
            cur.execute(
                """
                SELECT COUNT(*) AS qtd
                FROM requisicaoimagem ri
                JOIN requisicao r ON r.IdRequisicao = ri.IdRequisicao
                WHERE r.CodRequisicao = %s
                  AND ri.Inativo = 0
                  AND ri.Tipo = %s
                  AND UPPER(COALESCE(ri.ExtArquivo, '')) = 'PDF'
                """,
                (cod_requisicao, int(APLIS_TIPO_IMAGEM_GUIA)),
            )
            row = cur.fetchone() or {}
            cur.close()
            conn.close()
            return int(row.get("qtd") or 0) > 0
        except Exception as e:
            print(f"[APLIS-ANEXAR] Aviso: não foi possível verificar anexo pré-existente: {e}")
            return False

    def _buscar_ultimo_anexo_aplis_db(cod_requisicao: str):
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "3306")),
                user=os.getenv("DB_USER", "root"),
                password=os.getenv("DB_PASSWORD"),
                database=os.getenv("DB_NAME"),
            )
            cur = conn.cursor(dictionary=True)
            cur.execute(
                """
                SELECT
                    ri.IdRequisicaoImagem,
                    ri.IdRequisicao,
                    ri.Tipo,
                    ri.ExtArquivo,
                    ri.NomArquivo,
                    ri.Inativo
                FROM requisicaoimagem ri
                JOIN requisicao r ON r.IdRequisicao = ri.IdRequisicao
                WHERE r.CodRequisicao = %s
                  AND ri.Inativo = 0
                  AND ri.Tipo = %s
                  AND UPPER(COALESCE(ri.ExtArquivo, '')) = 'PDF'
                ORDER BY ri.IdRequisicaoImagem DESC
                LIMIT 1
                """,
                (cod_requisicao, int(APLIS_TIPO_IMAGEM_GUIA)),
            )
            row = cur.fetchone()
            cur.close()
            conn.close()
            if not row:
                return None
            return {
                "idRequisicaoImagem": row.get("IdRequisicaoImagem"),
                "idRequisicao": row.get("IdRequisicao"),
                "tipo": row.get("Tipo"),
                "extensao": row.get("ExtArquivo"),
                "arquivo": row.get("NomArquivo"),
                "inativo": row.get("Inativo"),
            }
        except Exception as e:
            print(f"[APLIS-ANEXAR] Aviso: não foi possível buscar metadados do anexo: {e}")
            return None

    if _ja_possui_guia_assinada_db(cod):
        msg = "Guia assinada já anexada anteriormente no APLIS para esta requisição."
        print(f"[APLIS-ANEXAR] {msg}")
        anexo_info = _buscar_ultimo_anexo_aplis_db(cod)
        return {
            "sucesso": True,
            "ja_anexado": True,
            "codRequisicao": cod,
            "mensagem": msg,
            "anexo_aplis": anexo_info,
        }

    # 1. Buscar documento no Autentique pelo nome
    print(f"[APLIS-ANEXAR] Buscando documento para requisição {cod} no Autentique...")
    try:
        docs_encontrados = buscar_documentos_por_nome(cod, limit=60)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao buscar no Autentique: {str(e)}"}

    if not docs_encontrados:
        return {
            "sucesso": False,
            "erro": "Nenhum documento encontrado no Autentique com esta requisição no nome",
            "detalhe": "Certifique-se de que o documento foi criado no Autentique com o número da requisição no nome"
        }

    uuid_doc = docs_encontrados[0].get("id")
    nome_doc = docs_encontrados[0].get("name", "")
    print(f"[APLIS-ANEXAR] Documento encontrado: {nome_doc} (ID: {uuid_doc})")

    # 2. Verificar status do documento
    try:
        doc_info = buscar_documento(uuid_doc)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao consultar documento no Autentique: {str(e)}"}

    if not doc_info.get("sucesso"):
        return {"sucesso": False, "erro": f"Falha ao consultar Autentique: {doc_info.get('erro')}"}

    url_assinado = doc_info.get("url_assinado", "")
    if not url_assinado:
        return {
            "sucesso": False,
            "erro": "Documento não possui PDF assinado disponível",
            "detalhe": f"Status: {doc_info.get('status')}. Todos assinaram? {doc_info.get('todos_assinaram')}"
        }

    # 3. Baixar o PDF
    print(f"[APLIS-ANEXAR] Baixando PDF assinado...")
    try:
        pdf_bytes = baixar_pdf_assinado(url_assinado)
    except Exception as e:
        return {"sucesso": False, "erro": f"Erro ao baixar PDF: {str(e)}"}

    if not pdf_bytes:
        return {"sucesso": False, "erro": "Falha ao baixar o PDF assinado do Autentique"}

    print(f"[APLIS-ANEXAR] PDF baixado: {len(pdf_bytes)} bytes")

    # 4. Buscar dados completos da requisicao no APLIS e reenviar com a imagem
    try:
        client = AplisClient()
        
        # Primeiro consulta os dados existentes da requisicao
        print(f"[APLIS-ANEXAR] Consultando dados da requisição {cod}...")
        status_resp = client._post("requisicaoStatus", {"codRequisicao": cod})
        status_dat = status_resp.get("dat", {})
        
        if status_dat.get("sucesso") != 1:
            return {
                "sucesso": False,
                "erro": f"Não foi possível consultar a requisição {cod} no APLIS",
                "detalhe": f"Código: {status_dat.get('codErro')} | {status_dat.get('msgErro')}"
            }
        
        print(f"[APLIS-ANEXAR] Dados obtidos: {json.dumps(status_dat, default=str)[:300]}")
        pdf_b64 = _b64.b64encode(pdf_bytes).decode("utf-8")

        def _build_admissao_payload_db(cod_requisicao: str):
            try:
                import mysql.connector

                conn = mysql.connector.connect(
                    host=os.getenv("DB_HOST", "localhost"),
                    port=int(os.getenv("DB_PORT", "3306")),
                    user=os.getenv("DB_USER", "root"),
                    password=os.getenv("DB_PASSWORD"),
                    database=os.getenv("DB_NAME"),
                )
                cur = conn.cursor(dictionary=True)
                cur.execute(
                    """
                    SELECT
                        IdRequisicao, IdLaboratorio, IdUnidade, CodPaciente,
                        IdConvenio, IdLocalOrigem, IdFontePagadora,
                        CodMedico, CodExame, NumGuiaConvenio,
                        SenhaAutorizacao, DtaColeta
                    FROM requisicao
                    WHERE CodRequisicao = %s
                    LIMIT 1
                    """,
                    (cod_requisicao,),
                )
                row = cur.fetchone()
                if not row:
                    cur.close()
                    conn.close()
                    return None

                testes_pat = []
                if row.get("IdRequisicao") is not None:
                    cur.execute(
                        "SELECT IdTeste FROM requisicaocaptura WHERE IdRequisicao = %s",
                        (row["IdRequisicao"],),
                    )
                    testes_pat = [
                        int(r["IdTeste"])
                        for r in cur.fetchall()
                        if r.get("IdTeste") is not None
                    ]

                cur.close()
                conn.close()

                if row.get("CodExame") is None:
                    return None

                dat = {
                    "codRequisicao": cod_requisicao,
                    "idLaboratorio": int(row.get("IdLaboratorio") or APLIS_ID_LABORATORIO),
                    "idUnidade": int(row["IdUnidade"]),
                    "idPaciente": int(row["CodPaciente"]),
                    "idConvenio": int(row["IdConvenio"]),
                    "idLocalOrigem": int(row["IdLocalOrigem"]),
                    "idFontePagadora": int(row["IdFontePagadora"]),
                    "idMedico": int(row["CodMedico"]),
                    "idExame": int(row["CodExame"]),
                    "examesConvenio": [int(row["CodExame"])],
                    "imagens": [
                        {
                            "tipo": int(APLIS_TIPO_IMAGEM_GUIA),
                            "extensao": "PDF",
                            "arquivo": pdf_b64,
                        }
                    ],
                }

                if row.get("NumGuiaConvenio"):
                    dat["numGuia"] = str(row["NumGuiaConvenio"])
                if row.get("SenhaAutorizacao"):
                    dat["senha"] = str(row["SenhaAutorizacao"])
                if row.get("DtaColeta"):
                    dat["dataColeta"] = row["DtaColeta"].strftime("%Y-%m-%d")
                if testes_pat:
                    dat["testesPatClinica"] = sorted(set(testes_pat))

                return dat
            except Exception as e:
                print(f"[APLIS-ANEXAR] Aviso: não foi possível montar payload via DB local: {e}")
                return None

        admissao_db = _build_admissao_payload_db(cod)
        if admissao_db:
            print("[APLIS-ANEXAR] Usando payload construído via DB local (requisicao/requisicaocaptura).")
            admissao_dat = admissao_db
        else:
            print("[APLIS-ANEXAR] Sem dados suficientes no DB local. Tentando fallback por requisicaoStatus.")

            def _limpar_escalar(valor):
                if valor is None:
                    return None
                if isinstance(valor, (dict, list, tuple, set)):
                    return None
                if isinstance(valor, str):
                    v = valor.strip()
                    if not v or v.lower() in ("null", "none", "undefined"):
                        return None
                    return v
                return valor

            def _norm_key(chave):
                return ''.join(ch for ch in str(chave or '').lower() if ch.isalnum())

            def _iter_dicts(obj):
                if isinstance(obj, dict):
                    yield obj
                    for v in obj.values():
                        yield from _iter_dicts(v)
                elif isinstance(obj, list):
                    for item in obj:
                        yield from _iter_dicts(item)

            all_dicts = list(_iter_dicts(status_dat))

            def _pick(*chaves):
                chaves_norm = {_norm_key(c) for c in chaves}
                for d in all_dicts:
                    for k, v in d.items():
                        if _norm_key(k) in chaves_norm:
                            vv = _limpar_escalar(v)
                            if vv is not None:
                                return vv
                return None

            def _pick_list(*chaves):
                chaves_norm = {_norm_key(c) for c in chaves}
                for d in all_dicts:
                    for k, v in d.items():
                        if _norm_key(k) in chaves_norm and isinstance(v, list):
                            return v
                return []

            # Monta payload de fallback usando o que houver no requisicaoStatus.
            imagens_existentes = _pick_list("imagens", "listaImagens", "imagensRequisicao")
            exames = _pick_list("exames", "listaExames", "itensExame", "itens")

            exames_sanitizados = []
            if isinstance(exames, list):
                for ex in exames:
                    if not isinstance(ex, dict):
                        continue
                    ex_limpo = {}
                    for k, v in ex.items():
                        vv = _limpar_escalar(v)
                        if vv is not None:
                            ex_limpo[k] = vv
                    if ex_limpo:
                        exames_sanitizados.append(ex_limpo)

            id_exame_extraido = _pick("idExame", "IdExame", "codExame", "CodExame", "idExameTipo", "CodExameTipo")

            if not id_exame_extraido and exames_sanitizados:
                ex0 = exames_sanitizados[0]
                id_exame_extraido = (
                    _limpar_escalar(ex0.get("idExame"))
                    or _limpar_escalar(ex0.get("IdExame"))
                    or _limpar_escalar(ex0.get("codExame"))
                    or _limpar_escalar(ex0.get("CodExame"))
                    or _limpar_escalar(ex0.get("idExameTipo"))
                    or _limpar_escalar(ex0.get("CodExameTipo"))
                )

            admissao_dat = {
                "codRequisicao": cod,
                "idLaboratorio": APLIS_ID_LABORATORIO,
                "idUnidade": _pick("idUnidade", "IdUnidade"),
                "idMedico": _pick("idMedico", "IdMedico"),
                "idConvenio": _pick("idConvenio", "IdConvenio"),
                "idLocalOrigem": _pick("idLocalOrigem", "IdLocalOrigem"),
                "idPrestadorOrigem": _pick("idPrestadorOrigem", "IdPrestadorOrigem"),
                "idFontePagadora": _pick("idFontePagadora", "IdFontePagadora"),
                "idTabelaPreco": _pick("idTabelaPreco", "IdTabelaPreco"),
                "idCobranca": _pick("idCobranca", "IdCobranca"),
                "idPaciente": _pick("idPaciente", "IdPaciente"),
                "idExame": id_exame_extraido,
                "idOrcamento": _pick("idOrcamento", "IdOrcamento"),
                "numGuia": _pick("numGuia", "NumGuia"),
                "senha": _pick("senha", "Senha"),
                "senha2": _pick("senha2", "Senha2"),
                "parcial": _pick("parcial", "Parcial"),
                "tipoAtendimento": _pick("tipoAtendimento", "TipoAtendimento"),
                "acomodacao": _pick("acomodacao", "Acomodacao"),
                "dataColeta": _pick("dataColeta", "DataColeta"),
                "dataColeta2": _pick("dataColeta2", "DataColeta2"),
                "exames": exames_sanitizados,
                "imagens": imagens_existentes + [
                    {
                        "tipo": int(APLIS_TIPO_IMAGEM_GUIA),
                        "extensao": "PDF",
                        "arquivo": pdf_b64,
                    }
                ],
            }

            if admissao_dat.get("idExame"):
                admissao_dat["examesConvenio"] = [admissao_dat["idExame"]]

            # Remove campos vazios para nao sobreescrever com null
            admissao_dat = {k: v for k, v in admissao_dat.items() if v is not None and v != '' and v != []}

            campos_criticos = [
                "idUnidade", "idPaciente", "idConvenio", "idLocalOrigem",
                "idFontePagadora", "idMedico", "idExame", "examesConvenio"
            ]
            faltantes = [c for c in campos_criticos if not admissao_dat.get(c)]

            if faltantes:
                print(
                    f"[APLIS-ANEXAR] Campos críticos ausentes em requisicaoStatus ({', '.join(faltantes)}). "
                    "Usando payload mínimo para anexar somente imagem."
                )
                admissao_dat = {
                    "codRequisicao": cod,
                    "idLaboratorio": APLIS_ID_LABORATORIO,
                    "imagens": admissao_dat["imagens"],
                }

        print(f"[APLIS-ANEXAR] Reenviando requisição {cod} com imagem anexada...")
        resultado = client._post("admissaoSalvar", admissao_dat)
        dat_resp = resultado.get("dat", {})

        if dat_resp.get("sucesso") != 1:
            msg_erro = str(dat_resp.get("msgErro") or "")
            if "SQLSTATE[42000]" in msg_erro or "FIND_IN_SET(" in msg_erro or "Selecione" in msg_erro:
                print("[APLIS-ANEXAR] Erro no payload atual. Tentando fallback com payload mínimo...")
                admissao_minima = {
                    "codRequisicao": cod,
                    "idLaboratorio": APLIS_ID_LABORATORIO,
                    "imagens": [
                        {
                            "tipo": int(APLIS_TIPO_IMAGEM_GUIA),
                            "extensao": "PDF",
                            "arquivo": pdf_b64,
                        }
                    ],
                }
                resultado = client._post("admissaoSalvar", admissao_minima)
                dat_resp = resultado.get("dat", {})
        
        if dat_resp.get("sucesso") == 1:
            print(f"[APLIS-ANEXAR] ✅ Sucesso! Requisição {cod} anexada.")
            anexo_info = _buscar_ultimo_anexo_aplis_db(cod)
            return {
                "sucesso": True,
                "codRequisicao": cod,
                "aplis_resposta": dat_resp,
                "anexo_aplis": anexo_info,
            }
        else:
            erro = f"[{dat_resp.get('codErro')}] {dat_resp.get('msgErro')}"
            print(f"[APLIS-ANEXAR] ❌ {erro}")
            debug = json.dumps({
                "status_dat": {k: str(v)[:120] for k, v in status_dat.items()},
                "payload_enviado": {k: str(v)[:120] for k, v in admissao_dat.items()}
            }, ensure_ascii=False, default=str)
            return {"sucesso": False, "erro": f"APLIS rejeitou: {erro}",
                    "detalhe": f"Debug:\n{debug}"}
    except Exception as e:
        return {"sucesso": False, "erro": f"Exceção ao anexar no APLIS: {str(e)}"}

# ── serve frontend buildado ────────────────────────────────────────────────────
FRONTEND_DIST = BASE_DIR / "frontend" / "dist"

if FRONTEND_DIST.exists():
    # Arquivos estáticos (JS, CSS, imagens)
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    # Arquivos estáticos na raiz do dist (logo.svg, favicon, etc.)
    @app.get("/{filename}", include_in_schema=False)
    def serve_root_static(filename: str):
        path = FRONTEND_DIST / filename
        if path.exists() and path.is_file():
            return FileResponse(path)
        return FileResponse(FRONTEND_DIST / "index.html")

    # Qualquer rota que não seja /api → devolve o index.html (SPA routing)
    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        return FileResponse(FRONTEND_DIST / "index.html")
else:
    @app.get("/", include_in_schema=False)
    def root():
        return {"msg": "Frontend não buildado. Rode: cd frontend && npm run build"}

_load_faturamento_exec_status()
_load_faturamento_baseline()
_load_gerenciamento_execucoes()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api:app", host="0.0.0.0", port=8001, reload=False)
