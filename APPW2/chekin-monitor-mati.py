#!/usr/bin/env python3
"""
chekin_monitor.py
=================
Monitoriza reservas de Chekin.io cada 30 minutos usando tu
usuario y contraseña normales (sin necesitar acceso API).

Estrategia:
  1. Playwright abre el navegador y se loguea con tus credenciales
  2. Intercepta el token JWT que el propio dashboard usa internamente
  3. Usa ese token para consultar la API directamente → datos limpios
  4. Clasifica huéspedes (BEBÉ/NIÑO/ADULTO), detecta cambios y guarda informe

INSTALACIÓN (una sola vez):
    pip install playwright requests python-dotenv schedule
    playwright install chromium

CONFIGURACIÓN:
    Crea un fichero .env con:
        CHEKIN_EMAIL=tu@email.com
        CHEKIN_PASSWORD=tupassword
"""

import os
import re
import sys
import json
import time
import logging
import smtplib
from email.mime.text import MIMEText
from datetime import datetime, date
from pathlib import Path

# Reconfigurar stdout/stderr a UTF-8 en Windows (cp1252 no muestra ─ ✅ 👶 etc.)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
import schedule
from dotenv import load_dotenv

# ── Playwright (importación diferida para mejor gestión de errores) ──────────
try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

# ──────────────────────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────────────────────
load_dotenv()

EMAIL         = os.getenv("CHEKIN_EMAIL", "")
PASSWORD      = os.getenv("CHEKIN_PASSWORD", "")
HEADLESS      = os.getenv("HEADLESS", "true").lower() != "false"  # False = ver el navegador
BASE_API      = "https://a.chekin.io/api/v4"
LOGIN_URL     = "https://chekin.com/onboarding/login/"      # WordPress + plugin ERF
DASHBOARD_URL = "https://dashboard.chekin.com/bookings"     # SPA post-login con JWT en localStorage
AJAX_URL      = "https://chekin.com/wp-admin/admin-ajax.php"
STATE_FILE    = "chekin_state_mati.json"
REPORT_FILE   = "chekin_report_mati.json"
TOKENS_FILE   = "chekin_tokens_mati.json"
HISTORY_FILE  = "chekin_history_mati.json"
INTERVAL_MIN  = 30

# Filtro: solo este apartamento
TARGET_APT    = "Villa Brisa Beach & Grill House"

# SMTP Gmail — destino fijo Matilde (override .env)
SMTP_HOST     = "smtp.gmail.com"
SMTP_PORT     = 587
EMAIL_SENDER  = os.getenv("EMAIL_SENDER", "")
EMAIL_PASS    = os.getenv("EMAIL_PASSWORD", "")
EMAIL_TO      = "matildelopezcanete@gmail.com"

# Umbrales de clasificación por edad (años cumplidos)
BEBE_MAX = 2     # ≤2   → BEBÉ
NINO_MAX = 15    # 3-15 → NIÑO  |  ≥16 → ADULTO

# Configuración de Email
EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECEIVER = os.getenv("EMAIL_RECEIVER", "")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# PASO 1 — Obtener token via Playwright (login web + interceptar red)
# ──────────────────────────────────────────────────────────────────────────────
def jwt_exp(token: str) -> float:
    """Devuelve timestamp UNIX de expiración del JWT, o 0 si no parseable."""
    try:
        import base64
        parts = token.split(".")
        if len(parts) < 2:
            return 0
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return float(data.get("exp", 0))
    except Exception:
        return 0


def save_tokens(access_token: str, refresh_token: str | None, cookies: list = None):
    """Persiste tokens y cookies en chekin_tokens.json."""
    Path(TOKENS_FILE).write_text(json.dumps({
        "access_token":  access_token,
        "refresh_token": refresh_token,
        "cookies":       cookies or [],
        "saved_at":      time.time(),
    }, indent=2))


def load_tokens() -> dict | None:
    p = Path(TOKENS_FILE)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def try_refresh(refresh_token: str) -> dict | None:
    """Intenta renovar access_token con refresh_token. Devuelve None si falla."""
    if not refresh_token:
        return None
    try:
        r = requests.post(
            f"{BASE_API}/login/refresh/",
            json={"refresh": refresh_token},
            headers={
                "Origin"       : "https://dashboard.chekin.com",
                "Referer"      : "https://dashboard.chekin.com/",
                "x-source"     : "DASHBOARD",
                "Content-Type" : "application/json",
                "Accept"       : "*/*",
            },
            verify=False,
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("access_token") or data.get("access"):
                log.info("✅ access_token renovado vía refresh_token.")
                return {
                    "access_token":  data.get("access_token") or data.get("access"),
                    "refresh_token": data.get("refresh_token") or data.get("refresh") or refresh_token,
                }
        log.warning(f"Refresh falló (HTTP {r.status_code}): {r.text[:200]}")
    except Exception as e:
        log.warning(f"Refresh error: {e}")
    return None


def get_token_via_browser(email: str, password: str) -> dict:
    """
    Flow manual-asistido (HEADLESS=false recomendado):

      1. Abre Chrome visible en https://chekin.com/onboarding/login/
      2. Usuario hace login manual (Cloudflare/Turnstile/Wordfence: vía humana)
      3. Script detecta redirect a dashboard.chekin.com/?auth_code=<UUID>
      4. Intercepta respuesta de /api/v4/login/exchange/ con tokens
      5. Devuelve access_token + refresh_token + cookies
    """
    if not PLAYWRIGHT_OK:
        raise RuntimeError(
            "Playwright no está instalado.\n"
            "Ejecuta:  pip install playwright && playwright install chromium"
        )

    # Windows: usa display nativo, no Xvfb
    xvfb_display = None

    log.info("=" * 70)
    log.info("Abriendo Chrome para login en Chekin (Mati).")
    log.info("INSTRUCCIONES:")
    log.info("  1. Se abre ventana Chrome.")
    log.info("  2. Login auto-completa si Cloudflare auto-pasa.")
    log.info("  3. Ventana se cierra sola tras capturar tokens.")
    log.info("=" * 70)
    captured = {"access_token": None, "refresh_token": None}

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(
                headless=False,
                channel="chrome",
                args=["--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"],
            )
        except Exception:
            browser = pw.chromium.launch(
                headless=False,
                args=["--ignore-certificate-errors", "--disable-blink-features=AutomationControlled"],
            )

        context = browser.new_context(
            ignore_https_errors=True,
            viewport={"width": 1280, "height": 900},
            locale="es-ES",
        )
        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        page = context.new_page()

        # Interceptar respuesta de login/exchange — captura tokens automáticamente
        def on_response(response):
            if "/api/v4/login/exchange" in response.url and response.status == 200:
                try:
                    j = response.json()
                    if j.get("access_token"):
                        captured["access_token"]  = j["access_token"]
                        captured["refresh_token"] = j.get("refresh_token")
                        log.info(f"✅ Tokens capturados ({len(j['access_token'])} chars)")
                except Exception as e:
                    log.warning(f"Parseando exchange: {e}")

        page.on("response", on_response)

        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=45_000)

        # Esperar a que form se renderice naturalmente (ERF JS attach handlers)
        try:
            page.wait_for_selector("#erf_username", timeout=20_000, state="visible")
        except PWTimeout:
            log.warning("Form login no visible tras 20s, sigo de todas formas.")

        # Auto-aceptar cookies y otros banners modales que bloquean el form
        for sel in [
            "#accept-cookies",
            "button#accept-cookies",
            "button:has-text(\"Aceptar todo\")",
            "button:has-text(\"Accept all\")",
            "button:has-text(\"Aceptar\")",
            "button:has-text(\"Accept\")",
            "button:has-text(\"OK\")",
            ".cookie-banner button",
        ]:
            try:
                btn = page.locator(sel).first
                if btn.is_visible(timeout=1000):
                    btn.click(timeout=2000)
                    log.info(f"✅ Banner cerrado: {sel}")
                    page.wait_for_timeout(500)
                    break
            except Exception:
                continue

        # Esperar a que Turnstile (Cloudflare) inyecte su token en el form (hasta 30s)
        log.info("Esperando token Cloudflare Turnstile…")
        turnstile_ok = False
        for _ in range(30):
            page.wait_for_timeout(1_000)
            v = page.evaluate("""() => {
                const el = document.querySelector('input[name="cf-turnstile-response"], textarea[name="cf-turnstile-response"]');
                return el ? (el.value || '').length : 0;
            }""")
            if v and v > 100:
                turnstile_ok = True
                log.info(f"✅ Turnstile token presente ({v} chars).")
                break

        if not turnstile_ok:
            log.warning("Turnstile no completó. Login puede fallar — pulsa manual si hace falta.")

        try:
            if email and password:
                log.info("Auto-fill credenciales…")
                page.locator("#erf_username").first.fill(email)
                page.locator("#erf_password").first.fill(password)
                page.wait_for_timeout(800)
                log.info("Auto-click Login…")
                page.locator(".erf-login-form button[type='submit']").first.click()
            else:
                log.info("Sin credenciales en .env. Login manual requerido.")
        except Exception as e:
            log.warning(f"Auto-submit falló, login manual: {e}")

        max_wait = 90 if xvfb_display is not None else 300
        log.info(f"Esperando captura tokens (timeout {max_wait}s)…")
        cookies = []
        try:
            deadline = time.time() + max_wait
            while time.time() < deadline:
                if captured["access_token"]:
                    break
                page.wait_for_timeout(250)
                if "dashboard.chekin.com" in page.url and not captured["access_token"]:
                    m = re.search(r"[?&]auth_code=([0-9a-f-]+)", page.url)
                    if m:
                        auth_code = m.group(1)
                        log.info(f"auth_code detectado en URL: {auth_code}")
                        try:
                            ex_resp = page.request.post(
                                f"{BASE_API}/login/exchange/",
                                data=json.dumps({"auth_code": auth_code}),
                                headers={
                                    "Content-Type": "application/json",
                                    "Origin":       "https://dashboard.chekin.com",
                                    "Referer":      "https://dashboard.chekin.com/",
                                    "x-source":     "DASHBOARD",
                                },
                            )
                            if ex_resp.status == 200:
                                j = ex_resp.json()
                                captured["access_token"]  = j.get("access_token")
                                captured["refresh_token"] = j.get("refresh_token")
                                log.info("✅ Tokens vía fallback exchange.")
                                break
                        except Exception as e:
                            log.warning(f"Fallback exchange falló: {e}")

            try:
                cookies = [
                    {"name": c["name"], "value": c["value"],
                     "domain": c["domain"], "path": c.get("path", "/")}
                    for c in context.cookies()
                ]
            except Exception as e:
                log.warning(f"No pude copiar cookies: {e}")
        finally:
            try:
                context.close()
            except Exception:
                pass
            try:
                browser.close()
            except Exception:
                pass
            log.info("🪟 Navegador cerrado.")

    if not captured["access_token"]:
        raise RuntimeError(
            "Timeout esperando login manual (5 min). Inténtalo de nuevo."
        )

    return {
        "access_token":  captured["access_token"],
        "refresh_token": captured["refresh_token"],
        "cookies":       cookies,
    }


# ──────────────────────────────────────────────────────────────────────────────
# PASO 2 — Cliente API que usa el token capturado
# ──────────────────────────────────────────────────────────────────────────────
class ChekinAPIClient:
    """
    Usa el token JWT obtenido por Playwright para consultar la API REST.
    Renueva el token automáticamente cada 55 minutos.
    """

    def __init__(self):
        self.token     = None
        self.token_ts  = 0
        self.session   = requests.Session()
        self.session.headers.update({
            "Accept"           : "*/*",
            "Accept-Language"  : "es",
            "Content-Type"     : "application/json",
            "Origin"           : "https://dashboard.chekin.com",
            "Referer"          : "https://dashboard.chekin.com/",
            "x-source"         : "DASHBOARD",
            "User-Agent"       : (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
        })
        self.session.verify = False
        requests.packages.urllib3.disable_warnings(
            requests.packages.urllib3.exceptions.InsecureRequestWarning
        )

    def ensure_token(self, force: bool = False):
        now = time.time()

        # 1) Cache en memoria: si access_token aún válido (con margen 60s), nada que hacer
        if not force and self.token and (now - self.token_ts) < 3300:
            return

        # 2) Tokens persistidos: cargar y comprobar expiración
        stored = load_tokens()
        if stored and not force:
            access = stored.get("access_token")
            refresh = stored.get("refresh_token")
            stored_cookies = stored.get("cookies", [])
            exp = jwt_exp(access) if access else 0
            # Si access_token aún válido, usarlo directamente
            if exp - now > 60:
                self._apply_creds(access, refresh, stored_cookies)
                log.info(f"Usando access_token persistido (expira en {int(exp-now)}s).")
                return
            # Si access expirado pero refresh válido, intentar renovar
            if refresh and jwt_exp(refresh) > now:
                renewed = try_refresh(refresh)
                if renewed:
                    save_tokens(renewed["access_token"], renewed["refresh_token"], stored_cookies)
                    self._apply_creds(renewed["access_token"], renewed["refresh_token"], stored_cookies)
                    return
                else:
                    log.info("Refresh falló, requiero login manual.")

        # 3) Sin tokens válidos → login manual asistido en navegador
        creds = get_token_via_browser(EMAIL, PASSWORD)
        save_tokens(creds["access_token"], creds["refresh_token"], creds.get("cookies", []))
        self._apply_creds(creds["access_token"], creds["refresh_token"], creds.get("cookies", []))

    def _apply_creds(self, access_token: str, refresh_token: str | None, cookies: list):
        self.token    = access_token
        self.token_ts = time.time()
        self.session.headers["authorization"] = f"JWT {access_token}"
        for c in cookies or []:
            try:
                self.session.cookies.set(
                    c["name"], c["value"],
                    domain=c.get("domain"), path=c.get("path", "/"),
                )
            except Exception:
                pass

    def get(self, endpoint: str, params: dict = None):
        self.ensure_token()
        url = f"{BASE_API}/{endpoint.lstrip('/')}"
        r   = self.session.get(url, params=params)

        if r.status_code == 401:
            log.warning("Token expirado, renovando…")
            self.ensure_token(force=True)
            r = self.session.get(url, params=params)

        r.raise_for_status()
        return r.json()

    def paginate(self, endpoint: str, params: dict = None) -> list:
        """Obtiene todas las páginas de un endpoint paginado."""
        data = self.get(endpoint, params)
        if isinstance(data, list):
            return data
        results = data.get("results", [])
        next_url = data.get("next")
        while next_url:
            self.ensure_token()
            r = self.session.get(next_url)
            r.raise_for_status()
            page = r.json()
            results.extend(page.get("results", []))
            next_url = page.get("next")
        return results

    def get_reservations(self) -> list:
        # Endpoint v4: /status/reservations/?ordering=-check_in_date
        return self.paginate("/status/reservations/", params={"ordering": "-check_in_date"})

    def get_guests(self, reservation_id: str, guest_group_id: str = "") -> list:
        # v4: huéspedes registrados están en /guest-groups/{ggid}/guests/
        if guest_group_id:
            try:
                return self.paginate(f"/guest-groups/{guest_group_id}/guests/")
            except requests.HTTPError:
                pass
        return []

    def get_guest_group(self, guest_group_id: str) -> dict:
        """Devuelve metadatos del grupo: adults, children, known/added counts."""
        if not guest_group_id:  
            return {}
        try:
            return self.get(f"/guest-groups/{guest_group_id}/")
        except requests.HTTPError:
            return {}

    def get_guest_detail(self, guest_id: str) -> dict:
        """Obtiene el detalle completo de un huésped."""
        try:
            return self.get(f"/guests/{guest_id}/")
        except requests.HTTPError:
            return {}

    def get_reservation_detail(self, reservation_id: str) -> dict:
        """Devuelve detalle completo: leader, phone, source, signup_form_link."""
        try:
            return self.get(f"/reservations/{reservation_id}/")
        except requests.HTTPError:
            return {}

    def get_housings(self) -> list:
        for path in ("/status/housings/", "/housings/"):
            try:
                return self.paginate(path)
            except requests.HTTPError:
                continue
        return []


# ──────────────────────────────────────────────────────────────────────────────
# PASO 3 — Clasificación de huéspedes
# ──────────────────────────────────────────────────────────────────────────────
def classify_age(dob_str: str) -> tuple[int | None, str]:
    """Devuelve (edad_en_años, tipo) donde tipo es BEBÉ/NIÑO/ADULTO/DESCONOCIDO."""
    if not dob_str:
        return None, "DESCONOCIDO"
    try:
        dob   = date.fromisoformat(dob_str[:10])
        today = date.today()
        age   = (today - dob).days // 365
        if age <= BEBE_MAX:
            return age, "BEBÉ"
        elif age <= NINO_MAX:
            return age, "NIÑO"
        else:
            return age, "ADULTO"
    except ValueError:
        return None, "DESCONOCIDO"


def build_guest(guest: dict) -> dict:
    dob_str = (guest.get("birth_date") or guest.get("date_of_birth")
               or guest.get("birthdate") or "")
    age, tipo = classify_age(dob_str)

    name = " ".join(filter(None, [
        guest.get("name") or guest.get("first_name", ""),
        guest.get("surname") or guest.get("last_name", ""),
    ])).strip() or "—"

    nationality = (guest.get("nationality") or guest.get("citizenship") or "—")
    statuses    = guest.get("statuses", {})
    reg_status  = statuses.get("data", "?") if isinstance(statuses, dict) else "?"

    return {
        "id"          : guest.get("id", ""),
        "nombre"      : name,
        "tipo"        : tipo,
        "edad"        : age,
        "fecha_nac"   : dob_str or "—",
        "nacionalidad": nationality,
        "doc_tipo"    : guest.get("document_type", "—"),
        "doc_numero"  : guest.get("document_number", "—"),
        "registro"    : reg_status,
    }


def build_reservation(res: dict, guests_raw: list, group_meta: dict = None,
                      detail: dict = None) -> dict:
    group_meta = group_meta or {}
    detail = detail or {}

    apt_name = (
        res.get("housing_display_name")
        or res.get("housing_name")
        or detail.get("housing_name")
        or "—"
    )
    apt_id = res.get("housing_id") or detail.get("housing_id") or "—"

    # Totales: prioridad → group_meta.known_number_of_guests
    total_guests = group_meta.get("known_number_of_guests", 0)
    registrados  = group_meta.get("added_number_of_guests", 0)
    if not total_guests:
        guests_str = res.get("guests", "")
        if isinstance(guests_str, str) and "/" in guests_str:
            try:
                registrados, total_guests = [int(x) for x in guests_str.split("/")]
            except Exception:
                pass

    # Clasificación a nivel grupo (sin distinguir bebés sin DOB individual)
    adults_g   = group_meta.get("adults", 0)
    children_g = group_meta.get("children", 0)

    # Huéspedes individuales (si registraron)
    huespedes = [build_guest(g) for g in guests_raw]
    resumen   = {"ADULTO": 0, "NIÑO": 0, "BEBÉ": 0, "DESCONOCIDO": 0}
    for h in huespedes:
        resumen[h["tipo"]] += 1
    # Si no hay individuales pero sí counts a nivel grupo, usar esos
    if not huespedes and (adults_g or children_g):
        resumen["ADULTO"] = adults_g
        resumen["NIÑO"]   = children_g

    check_in_raw  = (res.get("check_in_date") or res.get("check_in")
                     or detail.get("check_in_date") or "")
    check_out_raw = (res.get("check_out_date") or res.get("check_out")
                     or detail.get("check_out_date") or "")

    # Estado: si todos huéspedes registrados → COMPLETE, regardless of subitems
    api_status = res.get("general_status") or detail.get("status") or "—"
    if total_guests > 0 and registrados >= total_guests:
        estado_final = "COMPLETE"
    else:
        estado_final = api_status

    return {
        "id"            : res.get("id", ""),
        "apartamento"   : apt_name,
        "apartamento_id": apt_id,
        "check_in"      : (check_in_raw[:10] if check_in_raw else "—"),
        "check_out"     : (check_out_raw[:10] if check_out_raw else "—"),
        "num_huespedes" : total_guests,
        "registrados"   : registrados,
        "guest_leader"  : (detail.get("current_leader_full_name")
                           or res.get("guest_leader_name") or "—"),
        "telefono"      : detail.get("default_phone_number") or "—",
        "estado"        : estado_final,
        "estado_api"    : api_status,
        "fuente"        : detail.get("source_name") or res.get("external_id") or "—",
        "booking_ref"   : detail.get("booking_reference") or "—",
        "signup_link"   : detail.get("signup_form_link") or "",
        "updated_at"    : res.get("updated_at") or detail.get("modified", ""),
        "guest_group_id": res.get("guest_group_id") or "",
        "resumen"       : resumen,
        "huespedes"     : huespedes,
    }


# ──────────────────────────────────────────────────────────────────────────────
# PASO 4 — Persistencia y detección de cambios
# ──────────────────────────────────────────────────────────────────────────────
def load_state() -> dict:
    if Path(STATE_FILE).exists():
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def append_history(timestamp: str, changes: list):
    """Append-only log de cambios para historial / auditoría."""
    history = []
    p = Path(HISTORY_FILE)
    if p.exists():
        try:
            history = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            history = []
    history.append({"timestamp": timestamp, "changes": changes})
    p.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"📜 Histórico actualizado ({len(history)} entradas).")


def save_report(report: dict):
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    log.info(f"Informe guardado → '{REPORT_FILE}'")

def send_email(subject: str, body: str):
    """Envía correo vía SMTP Gmail."""
    if not EMAIL_SENDER or not EMAIL_PASSWORD or not EMAIL_RECEIVER:
        log.warning("Email no configurado en .env. Saltando envío.")
        return

    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = EMAIL_SENDER
        msg["To"] = EMAIL_RECEIVER

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        log.info(f"✅ Correo enviado a {EMAIL_RECEIVER}")
    except Exception as e:
        log.error(f"❌ Error enviando correo: {e}")


def detect_changes(old: dict, new_list: list) -> tuple[list, set]:
    """
    Solo notifica cuando reserva pasa a COMPLETE (todos huéspedes registrados).
    Devuelve (lista mensajes, set ids con transición).
    """
    changes = []
    mark_ids = set()
    for r in new_list:
        rid   = r["id"]
        prev  = old.get(rid, {})
        total = r.get("num_huespedes", 0)
        if (prev.get("estado") != "COMPLETE"
            and r.get("estado") == "COMPLETE"
            and total > 0):
            changes.append(
                f"✅  COMPLETO: todos {total} huéspedes registrados en "
                f"[{rid[:8]}…] {r['apartamento']} (entrada {r['check_in']})"
            )
            mark_ids.add(rid)
    return changes, mark_ids

    return changes


# ──────────────────────────────────────────────────────────────────────────────
# PASO 5 — Presentación en consola
# ──────────────────────────────────────────────────────────────────────────────
TIPO_EMOJI = {"ADULTO": "🧑", "NIÑO": "👦", "BEBÉ": "👶", "DESCONOCIDO": "❓"}

def print_report(report: dict):
    sep = "═" * 70
    print(f"\n{sep}")
    print(f"  CHEKIN.IO  │  {report['generado_en']}  │  "
          f"{report['total_reservas']} reservas")
    print(sep)

    for apt, reservas in report["apartamentos"].items():
        print(f"\n  🏠  {apt}")
        print("  " + "─" * 66)
        for r in reservas:
            s = r["resumen"]
            print(f"  📋 {r['id'][:8]}…  │  "
                  f"Entrada: {r['check_in']}  Salida: {r['check_out']}  │  "
                  f"Estado: {r['estado']}")
            print(f"       Huéspedes: {r['num_huespedes']}  "
                  f"(Adultos: {s['ADULTO']}  Niños: {s['NIÑO']}  "
                  f"Bebés: {s['BEBÉ']})")
            for h in r["huespedes"]:
                em  = TIPO_EMOJI.get(h["tipo"], "?")
                edad = f"{h['edad']}a" if h["edad"] is not None else "? a"
                print(f"         {em} {h['tipo']:<12} {h['nombre']:<28} "
                      f"{edad:<5}  {h['nacionalidad']:<4}  "
                      f"[doc:{h['doc_tipo']}]  [reg:{h['registro']}]")

    if report["cambios"]:
        print(f"\n  {'─'*66}")
        print("  🔔 CAMBIOS DETECTADOS:")
        for c in report["cambios"]:
            print(f"     {c}")

    print(f"\n{sep}\n")


# ──────────────────────────────────────────────────────────────────────────────
# Email summary via SMTP Gmail
# ──────────────────────────────────────────────────────────────────────────────
def _build_reservation_lines(r: dict) -> list:
    """Devuelve lista líneas de texto plano para una reserva."""
    s = r["resumen"]
    out = [
        f"  📋 {r['id'][:8]}…  │  "
        f"Entrada: {r['check_in']}  Salida: {r['check_out']}  │  "
        f"Estado: {r['estado']}",
        f"       Huéspedes: {r['num_huespedes']}  "
        f"(Adultos: {s['ADULTO']}  Niños: {s['NIÑO']}  Bebés: {s['BEBÉ']})",
        f"       Titular: {r.get('guest_leader','—')}  │  "
        f"Fuente: {r.get('fuente','—')}  │  Ref: {r.get('booking_ref','—')}",
    ]
    for h in r.get("huespedes", []):
        em   = TIPO_EMOJI.get(h["tipo"], "?")
        edad = f"{h['edad']}a" if h.get("edad") is not None else "? a"
        out.append(
            f"         {em} {h['tipo']:<12} {h['nombre']:<28} "
            f"{edad:<5}  {h['nacionalidad']:<4}"
        )
    return out


def send_email_summary(report: dict, mark_ids: set = None) -> bool:
    """
    Envía resumen vía SMTP Gmail con diseño responsive para móvil.
      mark_ids: ids reservas que dispararon cambio (verde)
      Reserva más próxima (check_in >= hoy más cercana) → marco amarillo
      Huéspedes BEBÉ → rojo
    """
    if not (EMAIL_SENDER and EMAIL_PASS and EMAIL_TO):
        log.warning("📧 Email no configurado (.env). Saltando envío.")
        return False

    mark_ids = mark_ids or set()
    import smtplib, html as _html
    from email.message import EmailMessage

    total      = report.get("total_reservas", 0)
    cambios    = report.get("cambios", [])
    apts       = report.get("apartamentos", {})
    generado   = report.get("generado_en", "")
    sep        = "═" * 70
    today_iso  = date.today().isoformat()

    # Reserva más próxima futura POR apartamento
    nearest_ids = set()
    for reservas in apts.values():
        best_id, best_date = None, None
        for r in reservas:
            ci = r.get("check_in", "")
            if ci and ci >= today_iso:
                if best_date is None or ci < best_date:
                    best_date = ci
                    best_id   = r["id"]
        if best_id:
            nearest_ids.add(best_id)

    # ── Cuerpo texto plano ──────────────────────────────────────────────
    lines = [sep, f"  CHEKIN.IO  │  {generado}  │  {total} reservas", sep]
    for apt, reservas in apts.items():
        lines.append("")
        lines.append(f"  🏠  {apt}")
        lines.append("  " + "─" * 66)
        for r in reservas:
            tag = ""
            if r["id"] in nearest_ids:
                tag += " ★PRÓXIMA"
            if r["id"] in mark_ids:
                tag += " 🆕NUEVA"
            block = _build_reservation_lines(r)
            if tag:
                block[0] = block[0] + tag
            lines.extend(block)

    if cambios:
        lines.append("")
        lines.append("  " + "─" * 66)
        lines.append("  🔔 CAMBIOS DETECTADOS:")
        for c in cambios:
            lines.append(f"     {c}")
    lines.append("")
    lines.append(sep)
    body_text = "\n".join(lines)

    # ── Construir HTML responsive para móvil ────────────────────────────
    html_parts = [
        '<!DOCTYPE html><html><head>'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '</head>'
        '<body style="margin:0;padding:0;background:#f4f4f4;'
        'font-family:Arial,Helvetica,sans-serif;color:#222;">'
        '<div style="max-width:580px;margin:0 auto;padding:8px 4px;">'
    ]
    html_parts.append(
        f'<div style="background:#1a73e8;color:#fff;padding:14px 16px;'
        f'border-radius:8px 8px 0 0;">'
        f'<div style="font-size:17px;font-weight:bold;">🏨 CHEKIN.IO</div>'
        f'<div style="font-size:12px;opacity:0.85;margin-top:3px;">'
        f'{_html.escape(generado)} &nbsp;·&nbsp; {total} reservas</div>'
        f'</div>'
    )
    for apt, reservas in apts.items():
        html_parts.append(
            f'<div style="background:#e8f0fe;padding:9px 14px;font-weight:bold;'
            f'font-size:14px;margin-top:10px;">'
            f'🏠 {_html.escape(apt)}</div>'
        )
        for r in reservas:
            s = r["resumen"]
            is_marked  = r["id"] in mark_ids
            is_nearest = r["id"] in nearest_ids

            if is_marked:
                card_bg  = "#e6f4ea"
                card_bdr = "#34a853"
            elif is_nearest:
                card_bg  = "#fef7e0"
                card_bdr = "#f9ab00"
            else:
                card_bg  = "#ffffff"
                card_bdr = "#dadce0"

            status_color = "#34a853" if r["estado"] == "COMPLETE" else "#888888"
            tags_html = ""
            if is_nearest:
                tags_html += ('<span style="background:#f9ab00;color:#fff;font-size:11px;'
                              'padding:2px 7px;border-radius:10px;margin-left:6px;">★ PRÓXIMA</span>')
            if is_marked:
                tags_html += ('<span style="background:#34a853;color:#fff;font-size:11px;'
                              'padding:2px 7px;border-radius:10px;margin-left:6px;">🆕 NUEVA</span>')

            bebe_style = "color:#d93025;font-weight:bold;" if s["BEBÉ"] > 0 else ""

            html_parts.append(
                f'<div style="background:{card_bg};border-left:4px solid {card_bdr};'
                f'padding:12px 14px;margin-bottom:2px;">'
            )
            html_parts.append(
                f'<div style="font-size:14px;font-weight:bold;margin-bottom:6px;">'
                f'📋 {_html.escape(r["id"][:8])}… '
                f'<span style="background:{status_color};color:#fff;font-size:11px;'
                f'padding:2px 8px;border-radius:10px;font-weight:normal;">'
                f'{_html.escape(r["estado"])}</span>{tags_html}</div>'
            )
            html_parts.append(
                f'<div style="font-size:14px;margin-bottom:5px;">'
                f'📅 <b>Entrada:</b> {_html.escape(r["check_in"])} &nbsp;'
                f'<b>Salida:</b> {_html.escape(r["check_out"])}</div>'
            )
            html_parts.append(
                f'<div style="font-size:14px;margin-bottom:5px;">'
                f'👥 {r["num_huespedes"]} &nbsp;·&nbsp; '
                f'🧑 {s["ADULTO"]} &nbsp;·&nbsp; '
                f'👦 {s["NIÑO"]} &nbsp;·&nbsp; '
                f'<span style="{bebe_style}">👶 {s["BEBÉ"]}</span></div>'
            )
            guest_mb = "6px" if r.get("huespedes") else "0"
            html_parts.append(
                f'<div style="font-size:13px;color:#555;margin-bottom:{guest_mb};">'
                f'👤 {_html.escape(r.get("guest_leader","—"))} &nbsp;·&nbsp; '
                f'🔖 {_html.escape(r.get("booking_ref","—"))}</div>'
            )
            for h in r.get("huespedes", []):
                em       = TIPO_EMOJI.get(h["tipo"], "?")
                edad_str = f'{h["edad"]}a' if h.get("edad") is not None else "?"
                g_style  = "color:#d93025;font-weight:bold;" if h["tipo"] == "BEBÉ" else "color:#333;"
                html_parts.append(
                    f'<div style="margin-top:4px;padding:5px 8px;background:rgba(0,0,0,0.04);'
                    f'border-radius:4px;font-size:13px;{g_style}">'
                    f'{em} <b>{_html.escape(h["tipo"])}</b> · '
                    f'{_html.escape(h["nombre"])} · {_html.escape(edad_str)} · '
                    f'{_html.escape(h["nacionalidad"])}</div>'
                )
            html_parts.append('</div>')

    if cambios:
        html_parts.append(
            '<div style="background:#e8f0fe;border-left:4px solid #1a73e8;'
            'padding:12px 14px;margin-top:12px;">'
            '<div style="font-weight:bold;font-size:14px;margin-bottom:8px;">'
            '🔔 CAMBIOS DETECTADOS</div>'
        )
        for c in cambios:
            html_parts.append(
                f'<div style="font-size:13px;padding:3px 0;">{_html.escape(c)}</div>'
            )
        html_parts.append('</div>')

    html_parts.append('</div></body></html>')
    body_html = "".join(html_parts)

    msg = EmailMessage()
    subject_tag = f" [{len(cambios)} cambios]" if cambios else ""
    msg["Subject"] = f"Chekin Monitor — {total} reservas{subject_tag}"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_TO
    msg.set_content(body_text)
    msg.add_alternative(body_html, subtype="html")

    # También adjuntar JSON del informe
    try:
        msg.add_attachment(
            json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8"),
            maintype="application", subtype="json",
            filename="chekin_report.json",
        )
    except Exception as e:
        log.warning(f"No se pudo adjuntar JSON: {e}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo()
            s.starttls()
            s.login(EMAIL_SENDER, EMAIL_PASS.replace(" ", ""))
            s.send_message(msg)
        log.info(f"📧 Email enviado a {EMAIL_TO}")
        return True
    except Exception as e:
        log.error(f"📧 Fallo al enviar email: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# Tarea principal
# ──────────────────────────────────────────────────────────────────────────────
api = ChekinAPIClient()


def send_auth_failure_alert(error_msg: str) -> bool:
    if not (EMAIL_SENDER and EMAIL_PASS and EMAIL_TO):
        return False
    import smtplib
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "⚠️ Chekin Monitor MATI — Token caducado, acción manual"
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_TO
    body = f"""El monitor no pudo refrescar el token automáticamente.

Error: {error_msg}

ACCIÓN REQUERIDA (en PC LOCAL):
  1. cd C:\\Users\\pmora\\chekin.com\\APP2
  2. .env: HEADLESS=false
  3. del chekin_tokens_mati.json
  4. python chekin-monitor-mati.py
  5. Chrome abre, login se completa, tokens guardados.
  6. scp chekin_tokens_mati.json root@servidor:/opt/app-mati/
  7. systemctl restart chekin-monitor-mati

Monitor reintentará cada 30 min sin éxito hasta entonces.
"""
    msg.set_content(body)
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
            s.ehlo(); s.starttls()
            s.login(EMAIL_SENDER, EMAIL_PASS.replace(" ", ""))
            s.send_message(msg)
        log.info(f"📧 Alerta auth enviada a {EMAIL_TO}")
        return True
    except Exception as e:
        log.error(f"No pude enviar alerta auth: {e}")
        return False


_LAST_ALERT_TS = 0
_ALERT_COOLDOWN_SEC = 6 * 3600


def run_check():
    log.info("─" * 50)
    log.info("Iniciando consulta…")
    old_state = load_state()

    try:
        raw_reservations = api.get_reservations()
        total_global = len(raw_reservations)
        raw_reservations = [
            r for r in raw_reservations
            if TARGET_APT in (r.get("housing_display_name", "") or "")
            or TARGET_APT in (r.get("housing_name", "") or "")
        ]
        log.info(f"  → {len(raw_reservations)}/{total_global} reservas (filtro: {TARGET_APT}).")

        processed = []
        for idx, res in enumerate(raw_reservations, 1):
            rid = res.get("id", "")
            log.info(f"  [{idx}/{len(raw_reservations)}] Obteniendo huéspedes de "
                     f"{rid[:8]}…")
            ggid       = res.get("guest_group_id", "") or ""
            guests_summary = api.get_guests(rid, ggid)

            # Enriquecer huéspedes con detalles individuales si existen
            guests_full = []
            for gs in guests_summary:
                gid = gs.get("id")
                if gid:
                    detail = api.get_guest_detail(gid)
                    if detail:
                        guests_full.append(detail)
                        continue
                guests_full.append(gs) # fallback al summary si falla el detalle

            group_meta = api.get_guest_group(ggid)
            detail     = api.get_reservation_detail(rid)
            processed.append(build_reservation(res, guests_full, group_meta, detail))

        changes, mark_ids = detect_changes(old_state, processed)
        new_state = {r["id"]: r for r in processed}

        # Agrupar por apartamento y ordenar por check_in
        apts: dict[str, list] = {}
        for r in processed:
            apts.setdefault(r["apartamento"], []).append(r)
        for apt in apts:
            apts[apt].sort(key=lambda x: x["check_in"])

        report = {
            "generado_en"   : datetime.now().isoformat(timespec="seconds"),
            "total_reservas": len(processed),
            "cambios"       : changes,
            "apartamentos"  : apts,
        }

        save_state(new_state)
        save_report(report)
        print_report(report)

        if changes:
            log.info(f"  🔔 {len(changes)} cambio(s) detectado(s).")
            append_history(report["generado_en"], changes)
            send_email_summary(report, mark_ids=mark_ids)
        else:
            log.info("  ✅ Sin cambios desde la consulta anterior. Email omitido.")

    except Exception as e:
        log.exception(f"Error en la consulta: {e}")
        msg = str(e).lower()
        if any(k in msg for k in ["token", "auth", "xvfb", "display", "playwright", "login"]):
            global _LAST_ALERT_TS
            now = time.time()
            if now - _LAST_ALERT_TS > _ALERT_COOLDOWN_SEC:
                send_auth_failure_alert(str(e)[:400])
                _LAST_ALERT_TS = now


# ──────────────────────────────────────────────────────────────────────────────
# Arranque
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not EMAIL or not PASSWORD:
        print("❌  Faltan credenciales. Crea un fichero .env con:")
        print("       CHEKIN_EMAIL=tu@email.com")
        print("       CHEKIN_PASSWORD=tupassword")
        raise SystemExit(1)

    log.info("Monitor Chekin.io arrancado.")
    log.info(f"  Intervalo  : cada {INTERVAL_MIN} minutos")
    log.info(f"  Estado     : {STATE_FILE}")
    log.info(f"  Informe    : {REPORT_FILE}")
    log.info(f"  Navegador  : {'headless' if HEADLESS else 'VISIBLE (depuración)'}")

    # Primera ejecución inmediata
    run_check()

    # Programar siguientes
    schedule.every(INTERVAL_MIN).minutes.do(run_check)
    log.info(f"Próxima consulta en {INTERVAL_MIN} min. Ctrl+C para salir.\n")

    while True:
        schedule.run_pending()
        time.sleep(30)
