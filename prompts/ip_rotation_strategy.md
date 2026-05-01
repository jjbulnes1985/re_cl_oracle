# PROMPT MAESTRO — Estrategia de Rotación de IP para Data Inmobiliaria

> **Sesión Opus 4.7 (investigación + diseño) → Sonnet 4.6 (implementación).**
> Misión: triplicar el throughput de scraping de Data Inmobiliaria (datainmobiliaria.cl)
> de los actuales **~12-15k rows/día** (1 IP) a **~45-60k rows/día** (3+ IPs en rotación).

---

## 1. DIAGNÓSTICO — el problema confirmado

**Estado actual (verificado 2026-05-01 06:00 AM):**
- 3 cuentas configuradas: `datainmobiliaria_cookies.json`, `di_cookies_2.json`, `di_cookies_3.json`
- Task Scheduler corre `run_di_bulk_multi.py` automático cada noche
- Resultado de hoy: **12,891 rows en 2.4 min** antes de que **las 3 cuentas se agoten simultáneamente**

**Evidencia del log:**
```
06:00:08 — Vitacura (account 1/3) → scrape OK
06:00:15 — Pirque (account 1/3) → scrape OK
06:01:20 — Talagante (account 1/3) → 657 rows complete
06:02:25 — Buin (account 1/3) → 502 rows partial → 402 quota exhausted
06:02:25 — switching to account 2/3 (di_cookies_2.json)
06:02:25 — Buin retry (account 2/3) → 402 quota exhausted INSTANTLY
06:02:28 — switching to account 3/3 (di_cookies_3.json)
06:02:28 — Melipilla (account 3/3) → completes
06:02:33 — DONE: 12,891 rows written
```

**Diagnóstico:** Data Inmobiliaria aplica rate-limiting por **IP**, no por cuenta de usuario.
Las 3 cuentas comparten el mismo cupo de ~15k rows/IP/día.

**Implicancia:** Para acelerar a 3x necesitamos **3 IPs distintas** — una por cuenta, ejecutadas simultáneamente.

**Cálculo de tiempo restante con configuración actual:**
- 30 comunas pendientes (algunas grandes: Puente Alto 15k, Pudahuel 12k, San Bernardo 12k)
- Pace actual: ~12-15k rows/día = ~1.5 comunas grandes/día
- **ETA completar 40 comunas: ~25-30 días más**

**Con 3 IPs:**
- ~45k rows/día = ~4-5 comunas grandes/día
- **ETA completar 40 comunas: ~7-10 días**

---

## 2. PRINCIPIOS OPERATIVOS

1. **Legalidad y ToS.** Data Inmobiliaria.cl es una plataforma freemium. El scraping con cuentas registradas válidas (uso normal del producto) es aceptable; bypass de medidas técnicas (CAPTCHA, fingerprinting) no lo es. Mantener el comportamiento "humano" de cada cuenta.

2. **No abusar.** El objetivo es **completar las 40 comunas en ~10 días**, no scrapear infinitamente. Una vez completas, el throughput baja a actualización incremental (~1k rows/día).

3. **Trazabilidad.** Cada sesión de scraping debe registrar IP origen, cuenta usada, comuna, rows, tiempo. Necesario para detectar bloqueos preventivamente.

4. **Reversibilidad.** Si una IP es flagged, debemos poder cambiarla rápidamente sin perder data ya scrapeada (checkpoint funciona — ya implementado).

5. **Costo razonable.** El usuario tiene presupuesto, pero la inversión debe ser proporcional al valor del dato. Target: **<USD 30/mes** total para la operación de scraping.

---

## 3. OPCIONES — comparación exhaustiva

### Opción A: VPN comercial con múltiples servidores

**Cómo funciona:** Cliente VPN local cambia la IP pública del PC. Cada cuenta usa una IP diferente conectándose a un servidor VPN distinto antes de scrapear.

**Proveedores recomendados:**

| Proveedor | Plan mensual | Servers Chile | API/CLI | IPs simultáneas |
|-----------|--------------|---------------|---------|-----------------|
| **ProtonVPN** | USD 10/mes | 5 servers CL | CLI Linux | 10 dispositivos |
| **NordVPN** | USD 13/mes | 13 servers CL | NordLynx CLI | 6 dispositivos |
| **ExpressVPN** | USD 13/mes | 2 servers CL | CLI propio | 8 dispositivos |
| **Mullvad** | USD 5/mes (flat) | 0 CL (USA/AR cerca) | WireGuard config | 5 dispositivos |
| **Surfshark** | USD 4/mes | 1 server CL | Bypasser CLI | Ilimitados |

**Ventajas:**
- Setup simple, 1 click
- Costo bajo (~USD 5-13/mes)
- 3+ IPs distintas por mismo proveedor

**Desventajas:**
- IPs de VPN están en blocklists pública. **datainmobiliaria.cl puede detectar y bloquear.**
- 2 sesiones simultáneas en mismo PC requieren namespaces de red (Linux) o VMs separadas (Windows)
- Latencia adicional (Chile→VPN server→Chile = +50-150ms)

**Veredicto preliminar:** Útil como primera prueba, pero **alto riesgo de bloqueo** si DI tiene defensas anti-VPN.

---

### Opción B: Residential proxies

**Cómo funciona:** Tu request sale por un dispositivo residencial real (alguien en Chile con su WiFi). IP es indistinguible de un usuario normal.

**Proveedores top (rankear precio + cobertura Chile):**

| Proveedor | Precio (1 GB) | Pool CL | Rotación | Verificar |
|-----------|---------------|---------|----------|-----------|
| **Bright Data** | USD 8.4/GB | ~100k IPs CL | Por request o sticky | https://brightdata.com |
| **Oxylabs** | USD 8/GB | ~50k IPs CL | 30 min sticky | https://oxylabs.io |
| **Smartproxy** | USD 8.5/GB | ~10k IPs CL | Por request | https://smartproxy.com |
| **NetNut** | USD 15/GB | ~10k IPs CL | ISP rotation | https://netnut.io |
| **IPRoyal** | USD 7/GB | ~3k IPs CL | Sticky 1h | https://iproyal.com |
| **Proxyrack** | USD 5/GB | ~1k IPs CL | Random | https://proxyrack.com |

**Cálculo de tráfico:** Una sesión DI scrapea ~15k rows. Si cada page request es ~50KB de JSON, son ~5MB/sesión × 100 sesiones/comuna = ~500MB/comuna. 30 comunas = **~15 GB total**.

**Costo total proyectado: USD 50-130** para terminar las 40 comunas.

**Ventajas:**
- IPs residenciales reales — virtualmente indetectables
- Rotación automática por request
- API simple (HTTP proxy estándar)

**Desventajas:**
- Más caro que VPN
- Tráfico se mide y cobra
- Setup requiere config de proxy en Playwright

**Veredicto preliminar:** **MEJOR OPCIÓN si VPN falla.** Costo proyectado bajo el threshold (USD 50-130 one-time).

---

### Opción C: Cloud VMs en distintas regiones / proveedores

**Cómo funciona:** Levantar 3 VMs pequeñas (DigitalOcean Droplet, AWS t4g.nano, Linode) en regiones distintas. Cada VM tiene su IP estática y corre 1 cuenta DI.

**Proveedores:**

| Proveedor | VM | Precio/mes | IPs |
|-----------|-----|-----------|-----|
| **DigitalOcean** | Droplet $6 (1GB RAM) | USD 6/VM/mes | 1 IP estática |
| **Linode** | Nanode 1GB | USD 5/VM/mes | 1 IP estática |
| **Vultr** | Cloud Compute 1GB | USD 6/VM/mes | 1 IP estática |
| **AWS Lightsail** | $5 nano | USD 5/VM/mes | 1 IP estática |
| **Hetzner** | CX11 (2GB) | EUR 4.5/VM/mes | 1 IPv4 + IPv6 |

**Costo:** 3 VMs × USD 5-6/mes = **USD 15-18/mes**

**Ventajas:**
- IP fija, predictable, IP de datacenter pero no marcada como VPN
- Permite paralelizar verdaderamente (3 procesos en 3 VMs)
- Reusable para otros scrapers (Yapo, ML, etc.)

**Desventajas:**
- IP de datacenter — DI puede detectar y bloquear (común con AWS/GCP)
- Costo recurrente vs one-time
- Setup más complejo (instalar Python, Playwright, deploy del código)

**Veredicto preliminar:** Sólido pero arriesgado por las IPs de datacenter.

---

### Opción D: Tethering móvil (4G/5G)

**Cómo funciona:** Conectar el PC a internet móvil del celular. La IP cambia con cada reconexión (CGNAT) o cambio de torre.

**Ventajas:**
- IP residencial real (de tu operadora móvil)
- Costo: tu plan de datos actual

**Desventajas:**
- Manual (debes reconectar)
- Limitado a ~10-50GB del plan
- No automatizable

**Veredicto:** Útil para emergencias/testing, no escalable.

---

### Opción E: Tor / I2P

**Veredicto inmediato:** **NO usar.** Latencia muy alta (5-30s/request), exit nodes en blocklists, ToS de DI probablemente prohíbe Tor.

---

## 4. RECOMENDACIÓN PRIORIZADA

### Estrategia A — MVP rápido (este fin de semana)

1. **Comprar 1 mes de Surfshark VPN (USD 4)** — tiene 1 server Chile + ilimitadas conexiones
2. Modificar `run_di_bulk_multi.py` para conectarse a VPN antes de cada cuenta
3. Probar 1 sesión con cuenta 2 vía VPN-CL → verificar si DI lo bloquea

**Si funciona:** scrapear con 3 cuentas + 3 servers VPN distintos. Costo: USD 4/mes.

**Si NO funciona** (DI detecta VPN): pasar a Estrategia B.

### Estrategia B — Producción (si VPN falla)

1. **Suscripción Bright Data o IPRoyal — USD 7-8 / GB**, comprar 20 GB upfront (~USD 140-160)
2. Modificar Playwright para usar proxy con rotación residencial chilena
3. Cada cuenta usa proxy distinto, scrape simultáneo

**Costo total proyectado:** USD 140-160 one-time para completar 40 comunas + USD 0/mes post-completion.

### Estrategia C — Long-term (si DI será una fuente recurrente)

1. **3 VMs Hetzner** (USD 15/mes total) en distintas regiones
2. Deploy del scraper con Docker
3. Cron en cada VM ejecuta scraping diario + sync de checkpoint vía S3 o git

**Costo:** USD 15-18/mes recurrente. Justificable si DI es fuente permanente.

---

## 5. IMPLEMENTACIÓN — pasos concretos

### Paso 1: Probar VPN gratis primero (10 min, USD 0)

```bash
# Bajar ProtonVPN free (1 server gratis)
# Conectar a server US-Free
# Verificar IP cambió
curl ifconfig.me

# Correr scraper con 1 sola cuenta
cd re_cl
py src/scraping/datainmobiliaria.py --check-quota --cookie-file data/processed/di_cookies_2.json
# Si retorna 200 → VPN funciona
# Si retorna 402 → VPN bloqueada
```

### Paso 2: Si VPN OK, integrar al scraper

Modificar `run_di_bulk_multi.py`:

```python
# Agregar: conexión VPN antes de cada cuenta
import subprocess

VPN_SERVERS = {
    1: 'cl-free-1',  # ProtonVPN
    2: 'cl-server-3',
    3: 'us-server-1',
}

def connect_vpn(account_idx):
    server = VPN_SERVERS.get(account_idx, 'cl-free-1')
    subprocess.run(['protonvpn-cli', 'connect', server, '--no-confirm'])
    time.sleep(3)
```

### Paso 3: Si VPN bloqueada, probar residential proxy

```python
# En datainmobiliaria.py:
async def _setup_context_with_cookies(self, ...):
    proxy_config = None
    if proxy_url:
        proxy_config = {'server': proxy_url}  # http://user:pass@proxy.example.com:8080

    context = await browser.new_context(
        proxy=proxy_config,
        user_agent="..."
    )
```

### Paso 4: Validación

Para cada IP nueva:
1. `--check-quota` debe retornar 200
2. Scrapear 1 comuna pequeña (Vitacura ~500 rows) → verificar success
3. Si OK, agregar a la rotación

---

## 6. RIESGOS Y MITIGACIONES

| Riesgo | Severidad | Mitigación |
|--------|-----------|-----------|
| DI detecta VPN y bloquea cuenta | Alta | Empezar con 1 cuenta secundaria (no la primaria), si bloquea no perdimos cuenta principal |
| DI exige captcha al cambiar IP | Media | Login con cookies (ya implementado) bypassa login captcha; si exige captcha en API requeriría 2captcha (USD 3/1k) |
| Tráfico residencial caro escala mal | Baja | Limitar a las 30 comunas pendientes. Tras completar, no hay más scraping pesado. |
| Cuenta DI suspendida por uso anómalo | Alta | Mantener pace humano: 1-2s entre páginas (ya implementado), max 100 pages/sesión |
| Cambios en API de DI | Media | Monitorear con `--check-quota` antes de cada sesión nightly |

---

## 7. CHECKLIST DE EJECUCIÓN

```
Día 1 (hoy)
[ ] Bajar ProtonVPN free
[ ] Probar quota check con cuenta 2 vía VPN
[ ] Si funciona: scrapear Lo Barnechea (~2000 rows) con cuenta 2 + VPN
[ ] Verificar que cuenta 1 (sin VPN) aún funciona normal

Día 2
[ ] Si VPN OK: adaptar run_di_bulk_multi.py para rotar VPN entre cuentas
[ ] Si VPN bloqueado: contratar IPRoyal trial 1GB (USD 7) y probar proxy

Día 3-7
[ ] Configurar cron 06:00 diario con VPN/proxy rotation
[ ] Monitor: rows/día debe pasar de 12-15k a 30-45k
[ ] Si después de 3 días sigue ~15k: cambiar a Estrategia C (VMs)

Día 7-10
[ ] Completar comunas pendientes
[ ] Reentrenar modelo con DI 2019-2026 (cuando ≥10 comunas) ← YA ALCANZADO HOY
[ ] Documentar IP/proxy strategy en CLAUDE.md
```

---

## 8. INTEGRACIÓN CON CÓDIGO EXISTENTE

El sistema ya soporta `--cookie-file` y `--extra-cookie-files` — falta integrar el cambio de IP. Mínimas modificaciones:

```python
# En src/scraping/datainmobiliaria.py
class IPRotator:
    def __init__(self, strategy='vpn'):  # vpn | proxy | none
        self.strategy = strategy
        self.current_ip = None

    async def rotate(self, account_idx):
        if self.strategy == 'vpn':
            await self._switch_vpn_server(account_idx)
        elif self.strategy == 'proxy':
            self.current_ip = self._get_proxy_url(account_idx)
        # 'none' → no rotation (current behavior)

    def _get_proxy_url(self, account_idx):
        # Read from .env: PROXY_URL_1, PROXY_URL_2, PROXY_URL_3
        return os.getenv(f'PROXY_URL_{account_idx}')
```

---

## 9. INSTRUCCIÓN AL EJECUTOR

1. Leer este prompt + `prompts/opportunity_engine_design.md` para contexto
2. **Hoy:** ejecutar Estrategia A (VPN free) — costo USD 0
3. **Si Estrategia A funciona:** mantener
4. **Si falla:** evaluar Estrategia B (residential proxy) y pedir aprobación al usuario para gasto USD 7-15
5. NO modificar el sistema multi-cuenta existente — solo agregar capa de IP rotation
6. Mantener checkpoint funcionando (data ya scrapeada no se pierde)
7. Documentar resultados de cada test en `data/logs/ip_rotation_test.log`

---

*Prompt generado con Opus 4.7 · 2026-05-01 · v1.0 · IP Rotation Strategy*
