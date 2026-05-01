# Setup de IP Rotation para Data Inmobiliaria

## Diagnóstico
Quota de DI es **por IP**, no por cuenta. Las 3 cuentas configuradas comparten el mismo cupo (~15k rows/día).
Para 3x throughput: necesitas 3 IPs distintas — una por cuenta.

## Estrategia A — VPN free (USD 0, prueba primero)

### Paso 1: Instalar ProtonVPN free
1. Crear cuenta gratis en https://protonvpn.com/free
2. Bajar cliente Windows desde la cuenta
3. Conectar al server `US-Free` (gratis incluye USA/Holanda/Japón)

### Paso 2: Probar quota con esa IP
```bash
cd re_cl
py scripts/test_proxy.py --account 2
```

**Resultado esperado:**
- `status: ok (200)` → ✅ DI no detecta VPN, podés usar
- `status: exhausted (402)` → ❌ Esa IP ya está marcada o agotó quota
- Si falla todo → DI bloquea VPN explícitamente

### Paso 3: Si funciona, integrar al nightly
Surfshark/NordVPN tienen CLI; ProtonVPN free solo tiene GUI manual.

**Opción manual (10 min/día):**
1. Conectar VPN antes de las 06:00 AM
2. Task Scheduler corre el nightly automático
3. Desconectar después

**Opción automatizada (NordVPN/Surfshark/Mullvad CLI):**
```bash
# Antes del nightly: conectar
nordvpn-cli connect cl
# El nightly corre normalmente
# Después: desconectar
nordvpn-cli disconnect
```

---

## Estrategia B — Residential proxy (USD 7-15, recomendado si VPN falla)

### Proveedor sugerido: IPRoyal (USD 7/GB, ~3k IPs Chile)

### Paso 1: Comprar plan
1. Registrarse en https://iproyal.com
2. Comprar 5 GB iniciales (~USD 35) para validar
3. Crear 3 sticky sessions con IPs distintas Chile

### Paso 2: Configurar `.env`
```bash
# En re_cl/.env
DI_PROXY_1=http://USER:PASS@geo.iproyal.com:12321
DI_PROXY_2=http://USER:PASS@geo.iproyal.com:12322
DI_PROXY_3=http://USER:PASS@geo.iproyal.com:12323
```

Donde `USER:PASS` son tus credenciales IPRoyal y los puertos van rotando IPs distintas (sticky session).

### Paso 3: Validar cada proxy
```bash
py scripts/test_proxy.py --account 1 --proxy http://USER:PASS@geo.iproyal.com:12321
py scripts/test_proxy.py --account 2 --proxy http://USER:PASS@geo.iproyal.com:12322
py scripts/test_proxy.py --account 3 --proxy http://USER:PASS@geo.iproyal.com:12323
```

Las 3 deben dar `status: ok` con IPs Chile distintas.

### Paso 4: Listo — el nightly los usa automáticamente
`run_di_bulk_multi.py` lee `DI_PROXY_1/2/3` del `.env` automáticamente.

```bash
# Forzar correr ahora (en vez de esperar 06:00)
py scripts/run_di_bulk_multi.py
```

---

## Estrategia C — VMs cloud (USD 15/mes recurrente)

### Si DI scraping será permanente (no solo completar 30 comunas)

3 Hetzner CX11 (EUR 4.5/VM/mes) en Frankfurt + Helsinki + Nuremberg = 3 IPs distintas.

```bash
# En cada VM:
git clone <repo>
cd re_cl
pip install -r requirements.txt
playwright install chromium

# Setup cron 06:00 + sync de checkpoint vía git push
crontab -e
0 6 * * * cd /home/jjb/re_cl && py scripts/run_di_bulk_multi.py >> nightly.log 2>&1
```

Cada VM corre 1 cuenta. El checkpoint se sincroniza vía git para evitar duplicados.

---

## Costos comparativos (completar 30 comunas pendientes)

| Estrategia | Setup time | Costo total | Throughput | Riesgo |
|-----------|-----------|------------|------------|--------|
| A — VPN free | 30 min | USD 0 | 30k/día (si funciona) | Alto (DI puede bloquear VPN) |
| A — VPN paga | 30 min | USD 4-13/mes | 30-45k/día | Medio |
| B — Residential proxy | 1 hora | USD 35-140 (one-time) | 45k/día | Bajo |
| C — VMs cloud | 4 horas | USD 15-18/mes | 45k/día | Bajo (datacenter IP, podría bloquear) |

**Recomendación:** Probar A free primero. Si DI bloquea VPN → ir a B (residential proxy IPRoyal 5 GB inicial).

---

## Verificación post-setup

Después de configurar, debés ver en el log nightly algo como:

```
Accounts configured: 3
  Account 1: datainmobiliaria_cookies.json
  Account 2: di_cookies_2.json
  Account 3: di_cookies_3.json
Proxies configured: 3/3
  Account 1: via geo.iproyal.com:12321
  Account 2: via geo.iproyal.com:12322
  Account 3: via geo.iproyal.com:12323
Starting bulk scrape...
  Vitacura (account 1/3) via proxy ... → 487 rows complete
  ... [scrape continues with 3 IPs simultáneamente]
DONE: 45,000 rows written in 8 min
```

vs. el actual sin proxies:
```
Accounts configured: 3
No proxies configured (set DI_PROXY_1, ... in .env)
  Account 1 → quota exhausted INSTANTLY
  Account 2 → quota exhausted INSTANTLY  ← misma IP
  Account 3 → quota exhausted
DONE: 12,891 rows written in 2.4min
```

---

## Reentrenamiento del modelo

Cuando completes ≥10 comunas DI (ya alcanzado hoy 2026-05-01), el modelo
se beneficia de reentrenar con datos 2019-2026. Comando:

```bash
py src/models/hedonic_model.py    # ya ejecutado 2026-05-01
py src/opportunity/add_hedonic_valuations.py
py src/opportunity/scoring_base.py
py src/opportunity/scoring_commercial.py
```

El modelo nuevo (R²=0.6712, n_train=520k) ya incluye datos DI 2019-2026.
