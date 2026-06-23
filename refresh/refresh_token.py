#!/usr/bin/env python3
"""
Captura tokens de Chekin.io con Chrome visible y los sube automáticamente
al servidor Linux. Ejecutar cuando llegue alerta de token caducado.
"""
import os, sys, json, time, re, io
from pathlib import Path
from dotenv import load_dotenv

_HERE = Path(__file__).parent
load_dotenv(_HERE / ".env")

# Try to also load Chekin credentials from APPW2/.env if it exists nearby
_appw2_env = _HERE.parent / "APPW2" / ".env"
if _appw2_env.exists():
    load_dotenv(_appw2_env, override=False)

CHEKIN_EMAIL = os.getenv("CHEKIN_EMAIL", "")
CHEKIN_PASS  = os.getenv("CHEKIN_PASSWORD", "")
SERVER_HOST  = os.getenv("SERVER_HOST", "192.168.0.146")
SERVER_USER  = os.getenv("SERVER_USER", "root")
SERVER_PASS  = os.getenv("SERVER_PASS", "")
SERVER_PATH  = os.getenv("SERVER_PATH", "/opt/app-mati/chekin_tokens_mati.json")
TOKENS_LOCAL = _HERE / "chekin_tokens_mati.json"  # saved in refresh/ folder
BASE_API     = "https://a.chekin.io/api/v4"
LOGIN_URL    = "https://chekin.com/onboarding/login/"


def ok(msg):  print(f"    ✅ {msg}")
def warn(msg): print(f"    ⚠️  {msg}")
def err(msg):  print(f"    ❌ {msg}")


def capture_token() -> dict:
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        err("playwright no instalado. Ejecuta: pip install playwright && playwright install chromium")
        sys.exit(1)

    print("\n[1/3] Abriendo Chrome para login en Chekin...")
    print("      (Completa el login si Cloudflare lo pide manualmente)")
    captured = {"access_token": None, "refresh_token": None}

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=False, channel="chrome",
                args=["--ignore-certificate-errors",
                      "--disable-blink-features=AutomationControlled"])
        except Exception:
            browser = pw.chromium.launch(
                headless=False,
                args=["--ignore-certificate-errors",
                      "--disable-blink-features=AutomationControlled"])

        ctx = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            locale="es-ES")
        ctx.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        page = ctx.new_page()

        def on_response(resp):
            if "/api/v4/login/exchange" in resp.url and resp.status == 200:
                try:
                    j = resp.json()
                    if j.get("access_token"):
                        captured["access_token"]  = j["access_token"]
                        captured["refresh_token"] = j.get("refresh_token")
                        ok(f"Tokens capturados ({len(j['access_token'])} chars).")
                except Exception:
                    pass

        page.on("response", on_response)
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)

        try:
            page.wait_for_selector("#erf_username", timeout=20_000, state="visible")
        except PWTimeout:
            warn("Formulario tardó en aparecer, continuando...")

        print("      Esperando Cloudflare Turnstile...")
        for _ in range(30):
            page.wait_for_timeout(1_000)
            v = page.evaluate("""() => {
                const el = document.querySelector(
                  'input[name="cf-turnstile-response"],textarea[name="cf-turnstile-response"]');
                return el ? (el.value||'').length : 0;
            }""")
            if v and v > 100:
                ok("Turnstile completado.")
                break

        try:
            if CHEKIN_EMAIL and CHEKIN_PASS:
                page.locator("#erf_username").first.fill(CHEKIN_EMAIL)
                page.locator("#erf_password").first.fill(CHEKIN_PASS)
                page.wait_for_timeout(800)
                page.locator(".erf-login-form button[type='submit']").first.click()
                print("      Login enviado automáticamente...")
        except Exception as e:
            warn(f"Auto-login falló, complétalo en Chrome: {e}")

        print("      Esperando tokens (máx 5 min)...")
        cookies = []
        deadline = time.time() + 300
        try:
            while time.time() < deadline:
                if captured["access_token"]:
                    break
                page.wait_for_timeout(250)
                if "dashboard.chekin.com" in page.url and not captured["access_token"]:
                    m = re.search(r"[?&]auth_code=([0-9a-f-]+)", page.url)
                    if m:
                        try:
                            import requests
                            ex = requests.post(
                                f"{BASE_API}/login/exchange/",
                                json={"auth_code": m.group(1)},
                                headers={"Content-Type": "application/json",
                                         "Origin": "https://dashboard.chekin.com",
                                         "x-source": "DASHBOARD"},
                                verify=False, timeout=15)
                            if ex.status_code == 200:
                                j = ex.json()
                                captured["access_token"]  = j.get("access_token")
                                captured["refresh_token"] = j.get("refresh_token")
                                ok("Tokens obtenidos via exchange.")
                                break
                        except Exception:
                            pass
            try:
                cookies = [
                    {"name": c["name"], "value": c["value"],
                     "domain": c["domain"], "path": c.get("path", "/")}
                    for c in ctx.cookies()
                ]
            except Exception:
                pass
        finally:
            try: ctx.close()
            except: pass
            try: browser.close()
            except: pass
            print("      Navegador cerrado.")

    if not captured["access_token"]:
        err("Timeout: no se capturaron tokens en 5 min.")
        sys.exit(1)

    return {
        "access_token":  captured["access_token"],
        "refresh_token": captured["refresh_token"],
        "cookies":       cookies,
        "saved_at":      time.time(),
    }


def upload_to_server(tokens: dict):
    print(f"\n[2/3] Subiendo tokens al servidor {SERVER_HOST}...")
    try:
        import paramiko
    except ImportError:
        err("paramiko no instalado. Ejecuta: pip install paramiko")
        sys.exit(1)

    content = json.dumps(tokens, ensure_ascii=False, indent=2).encode("utf-8")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(SERVER_HOST, username=SERVER_USER,
                    password=SERVER_PASS, timeout=10)

        sftp = ssh.open_sftp()
        sftp.putfo(io.BytesIO(content), SERVER_PATH)
        sftp.close()
        ok(f"Tokens subidos → {SERVER_HOST}:{SERVER_PATH}")

        print("\n[3/3] Reiniciando servicio en el servidor...")
        _, stdout, stderr = ssh.exec_command(
            "systemctl restart chekin-monitor-mati && echo REINICIADO")
        exit_code = stdout.channel.recv_exit_status()
        output = stdout.read().decode().strip()
        if "REINICIADO" in output or exit_code == 0:
            ok("Servicio reiniciado correctamente.")
        else:
            warn(f"Reinicio puede haber fallado: {stderr.read().decode()[:200]}")

        ssh.close()

    except Exception as e:
        err(f"No se pudo conectar al servidor ({SERVER_HOST}): {e}")
        print(f"\n      Copia manualmente con estos comandos:")
        print(f"      scp {TOKENS_LOCAL} {SERVER_USER}@{SERVER_HOST}:{SERVER_PATH}")
        print(f"      ssh {SERVER_USER}@{SERVER_HOST} systemctl restart chekin-monitor-mati")
        input("\nPresiona Enter para salir...")
        sys.exit(1)


if __name__ == "__main__":
    print("=" * 52)
    print("  CHEKIN.IO — Renovar Token de Acceso")
    print("=" * 52)

    tokens = capture_token()

    TOKENS_LOCAL.write_text(
        json.dumps(tokens, ensure_ascii=False, indent=2), encoding="utf-8")
    ok(f"Copia local guardada → {TOKENS_LOCAL}")

    upload_to_server(tokens)

    print("\n" + "=" * 52)
    print("  ✅ Token renovado y servicio reiniciado.")
    print("=" * 52)
    input("\nPresiona Enter para cerrar...")
