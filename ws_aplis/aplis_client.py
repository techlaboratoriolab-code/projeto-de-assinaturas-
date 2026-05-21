"""
Cliente da API APLIS - Integração v2
Referência: apLIS - API Integração v2

Endpoint único: POST {BASE_URL}/api/integracao.php
Formato: {"ver": 2, "cmd": "...", "dat": {...}}
"""

import base64
import json
import requests
from datetime import datetime
from pathlib import Path
from config_ws import (
    APLIS_API_URL, APLIS_LOGOUT_URL, APLIS_API_VER,
    APLIS_USER, APLIS_PASS, APLIS_ID_LABORATORIO, APLIS_TIPO_IMAGEM_GUIA
)


class AplisClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        self._logado = False

    def _post(self, cmd: str, dat: dict) -> dict:
        payload = {"ver": APLIS_API_VER, "cmd": cmd, "dat": dat}
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        # Tenta como JSON primeiro, com Basic Auth caso o servidor exija
        try:
            resp = self.session.post(
                APLIS_API_URL,
                json=payload,
                headers=headers,
                auth=requests.auth.HTTPBasicAuth(APLIS_USER, APLIS_PASS),
                timeout=30,
            )
            try:
                data = resp.json()
                return data
            except ValueError:
                pass
            body = resp.text[:500]
            return {"dat": {"sucesso": 0, "codErro": resp.status_code, "msgErro": f"HTTP {resp.status_code}: {body}"}}
        except requests.exceptions.Timeout:
            return {"dat": {"sucesso": 0, "codErro": -1, "msgErro": "Timeout ao conectar no APLIS"}}
        except requests.exceptions.ConnectionError as e:
            return {"dat": {"sucesso": 0, "codErro": -1, "msgErro": f"Falha de conexao: {str(e)}"}}
        except Exception as e:
            return {"dat": {"sucesso": 0, "codErro": -3, "msgErro": f"Erro inesperado: {str(e)}"}}

    def login(self) -> bool:
        """Autentica na API APLIS via login/senha."""
        if not APLIS_USER or not APLIS_PASS:
            print("⚠ APLIS_USER ou APLIS_PASS não configurados")
            return False

        resultado = self._post("login", {"login": APLIS_USER, "senha": APLIS_PASS})
        dat = resultado.get("dat", {})

        if dat.get("sucesso") == 1:
            self._logado = True
            print("[OK] Login APLIS efetuado")
            return True

        print(f"[ERR] Falha no login APLIS: [{dat.get('codErro')}] {dat.get('msgErro')}")
        return False

    def logout(self):
        """Encerra a sessão na API APLIS."""
        try:
            self.session.get(APLIS_LOGOUT_URL, timeout=10)
        except Exception:
            pass
        self._logado = False

    def requisicao_status(self, cod_requisicao: str) -> dict:
        """Consulta o status da requisição (cmd: requisicaoStatus)."""
        resultado = self._post("requisicaoStatus", {"codRequisicao": cod_requisicao})
        dat = resultado.get("dat", {})

        if dat.get("sucesso") == 1:
            print(f"[OK] Status da requisição {cod_requisicao} obtido")
        else:
            print(f"[ERR] Erro ao buscar status: [{dat.get('codErro')}] {dat.get('msgErro')}")

        return dat

    def anexar_guia_assinada(self, cod_requisicao: str, pdf_bytes: bytes) -> dict:
        """
        Anexa o PDF da guia assinada à requisição via admissaoSalvar.
        """
        pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")

        # Segundo a documentação, apenas codRequisicao e imagens são necessários para atualização.
        # idLaboratorio é obrigatório na criação, mas vamos manter por segurança.
        dat = {
            "codRequisicao": cod_requisicao,
            "idLaboratorio": APLIS_ID_LABORATORIO,
            "imagens": [
                {
                    "tipo": 5, # Alterado para 5 (Documento) conforme página 5 da documentação
                    "extensao": "PDF",
                    "arquivo": pdf_b64,
                }
            ],
        }

        print(f"📎 Anexando guia assinada à requisição {cod_requisicao} (Tipo 5)...")
        resultado = self._post("admissaoSalvar", dat)
        dat_resp = resultado.get("dat", {})

        if dat_resp.get("sucesso") == 1:
            print(f"[OK] Guia anexada com sucesso → requisição {dat_resp.get('codRequisicao')}")
        else:
            # Se falhou, tenta logar novamente e repetir uma única vez (sessão pode ter expirado)
            print(f"[WARN] Falha na primeira tentativa de anexo ([{dat_resp.get('codErro')}]). Tentando re-login...")
            self._logado = False
            if self.login():
                resultado = self._post("admissaoSalvar", dat)
                dat_resp = resultado.get("dat", {})
                if dat_resp.get("sucesso") == 1:
                    print(f"[OK] Guia anexada com sucesso após re-login")
                    return dat_resp

            print(f"[ERR] Falha ao anexar guia: [{dat_resp.get('codErro')}] {dat_resp.get('msgErro')}")

        return dat_resp

    def requisicao_listar(self, periodo_ini: str, periodo_fim: str,
                          num_guia: str = "", pagina: int = 1, tamanho: int = 50) -> dict:
        """Lista requisições no período. Data formato: AAAA-MM-DD."""
        dat = {
            "tipoData": 1,
            "periodoIni": periodo_ini,
            "periodoFim": periodo_fim,
            "pagina": pagina,
            "tamanho": tamanho,
        }
        if num_guia:
            dat["numGuia"] = num_guia

        return self._post("requisicaoListar", dat).get("dat", {})


# Instância singleton para reutilizar sessão
_client = None


def get_client() -> AplisClient:
    global _client
    if _client is None:
        _client = AplisClient()
        _client.login()
    return _client
