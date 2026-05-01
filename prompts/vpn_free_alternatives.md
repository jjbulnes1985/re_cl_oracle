# Alternativas gratuitas reales para IP rotation DI

> **Diagnóstico:** ProtonVPN free es lento e ineficiente. Servidores gratuitos saturados, latencia +200ms, conexiones intermitentes. Necesitamos algo realmente gratis y útil.

---

## Opción 1 — **Tethering del celular** (la más simple, recomendada)

### Por qué funciona
- IP **residencial real** (de tu operador móvil) — DI no detecta como VPN
- Distinta a tu IP doméstica (Movistar/Entel/WOM/Claro asignan IPs CGNAT pero rotativas)
- Cada vez que reconectas el WiFi del celular puedes obtener IP nueva (avión-mode → reconectar)

### Setup
1. Activar "Punto de acceso" o "Compartir conexión" en celular (5G/4G)
2. Conectar el PC al WiFi del celular (NO al WiFi doméstico)
3. Verificar IP nueva: `curl ifconfig.me`
4. Correr el scraping con cuenta 2

### Costo
- **USD 0** si tienes plan ilimitado
- **~30 MB por sesión scraping** = 1 GB ≈ 30 sesiones (casi todo el plan mensual)

### Pros / Contras
- ✓ IP residencial perfecta, indetectable
- ✓ Cero configuración técnica
- ✓ Funciona desde día 1
- ✗ Requiere intervención manual (cambiar WiFi)
- ✗ Limitado a tu plan de datos
- ✗ No automatizable con Task Scheduler (a menos que el PC esté siempre en WiFi del cel)

**Veredicto:** mejor opción para hoy. Hace **3 comunas hoy + 3 mañana** = completas las 30 en 10 días.

---

## Opción 2 — **Cloudflare Warp+** (gratis, rápido, latencia baja)

### Setup
1. Bajar Cloudflare WARP en https://1.1.1.1
2. Activar "Warp" (no es VPN tradicional pero enmascara IP)
3. Tu IP se ve como una IP de Cloudflare (datacenter)

### Pros / Contras
- ✓ Gratis siempre, sin límite de datos
- ✓ Rápido (Cloudflare backbone, latencia <50ms)
- ✓ Setup en 30 segundos
- ✗ IP de datacenter — **DI puede detectar y bloquear** como VPN
- ✗ Solo 1 IP (no permite rotación entre cuentas)

**Probar primero:** instala WARP, abre `curl ifconfig.me` para ver IP, corre `py scripts/test_proxy.py --account 2`. Si retorna 200, úsalo. Si retorna 402, descartar.

---

## Opción 3 — **Oracle Cloud Always Free** (lo más profesional gratis)

### Por qué Oracle y no AWS
- AWS Free Tier dura solo 12 meses, después cobra
- **Oracle Cloud da 4 VMs ARM gratis para siempre** (sin tarjeta de crédito requerida tras setup)
- 24 GB RAM total, 4 OCPU, 200 GB disco gratis siempre

### Setup
1. Crear cuenta en https://oracle.com/cloud/free
2. Crear 3 VMs Ampere (ARM) en regiones distintas:
   - Phoenix (US)
   - Ashburn (US)
   - Frankfurt (EU)
3. Cada VM tiene IP estática propia
4. Deploy del scraper en cada VM (1 cuenta por VM)
5. Cron job 06:00 en cada VM ejecuta scraping diario

### Configurar
```bash
# En cada VM Oracle:
sudo apt update && sudo apt install -y python3-pip git
git clone https://github.com/<tu-fork>/RE_CL.git
cd RE_CL/re_cl
pip install -r requirements.txt
playwright install chromium
# Copiar las cookies di_cookies_N.json
# Cron 06:00:
echo "0 6 * * * cd /home/ubuntu/RE_CL/re_cl && py scripts/run_di_bulk_multi.py >> nightly.log 2>&1" | crontab -
```

### Pros / Contras
- ✓ Gratis para siempre
- ✓ 3 IPs distintas (3 datacenters), automático 24/7
- ✓ Triplicas el throughput sin tu PC encendido
- ✗ IP de datacenter — riesgo similar a Cloudflare (verificar primero)
- ✗ Setup técnico inicial (~1 hora)

---

## Opción 4 — **Hotspot WiFi de cafetería / espacios públicos**

### Por qué funciona
- Cada lugar tiene IP residencial distinta del proveedor (Mundo, GTD, VTR)
- **Quota DI se basa en IP** → cada nueva red = quota fresca

### Cómo
- Llevar el laptop a Starbucks / Café / coworking 1 día
- Conectarse a WiFi del lugar
- Correr scraping (15-20 min)
- Volver a casa

### Pros / Contras
- ✓ IP residencial real, totalmente legítima
- ✓ Costo: USD 5 (un café)
- ✗ No automatizable, requiere desplazarse
- ✗ Puede ser lento

**Veredicto:** bueno para acelerar 1 vez. Si quieres scrapear 5 comunas grandes en una sesión, vas a un café y listo.

---

## Opción 5 — **Reiniciar el módem** (gratis, casero)

### Por qué a veces funciona
- Algunas operadoras (Movistar, Entel) asignan IPs dinámicas
- Reiniciar router → IP nueva del pool
- DI ve IP "nueva" → quota fresca

### Cómo
1. Apagar router 2 minutos
2. Encender → verificar IP cambió: `curl ifconfig.me`
3. Si cambió, scraping con cuenta diferente

### Pros / Contras
- ✓ Gratis, en casa
- ✗ Algunas operadoras dan IP fija (CGNAT)
- ✗ Solo 1 IP nueva por reinicio
- ✗ Cliente del internet doméstico cae 2 min

---

## Recomendación priorizada

```
Hoy mismo (sin setup):
  1. Tethering celular              → 1 sesión adicional/día
  2. Probar Cloudflare WARP         → si funciona, simple

Esta semana (1 hora setup):
  3. Oracle Cloud 3 VMs gratis      → automatización 24/7
  4. Café WiFi 1 día                → 5 comunas grandes en 1 sesión

Si nada funciona:
  5. Reset módem ocasional          → 1 sesión extra/semana
  6. Pagar IPRoyal USD 35-140       → única opción confiable comercial
```

---

## Estrategia híbrida (lo más eficiente)

**Plan de 7-10 días para completar las 30 comunas:**

| Día | Lugar/método | IPs distintas | Comunas estimadas |
|-----|--------------|---------------|-------------------|
| 1   | Casa (IP normal) | 1 | 4-5 |
| 2   | Casa + tethering celular | 2 | 8-10 |
| 3   | Casa + WARP | 2 | 7-9 |
| 4   | Café WiFi | 1 | 4-5 |
| 5-7 | Oracle Cloud (24/7 auto) | 3 | 12-15 |
| 8-10| Buffer + reintentos | — | 5-8 |

**Total estimado:** completas las 30 comunas RM en ~10 días sin pagar nada.

---

## Setup rápido — TETHERING (5 minutos)

### Pre-requisitos
- Plan de datos celular con tethering habilitado
- Cable USB o WiFi del celular activado

### Paso a paso
1. Celular: ajustes → conexiones → punto de acceso WiFi → activar
2. PC: desconectar del WiFi de la casa → conectar al WiFi del celular
3. Verificar IP nueva:
   ```bash
   cd re_cl
   py scripts/test_proxy.py --account 2
   # Debería retornar "OK (200)"
   ```
4. Si OK, scrapear:
   ```bash
   py scripts/run_di_bulk_multi.py
   # Usa cuentas 2 y 3 con IP del cel (la 1 puede estar agotada)
   ```

### Después de cada sesión
- Reconectar PC al WiFi de casa
- Modo avión 30s en cel para forzar IP nueva (próxima vez)

---

## Setup detallado — ORACLE CLOUD (60 minutos, una vez)

### Crear cuenta
1. https://signup.cloud.oracle.com/
2. Tarjeta de crédito requerida para verificación (NO se cobra nada)
3. Esperar email de activación (~10 min)

### Crear 3 VMs ARM gratis
1. Compute → Instances → Create instance
2. Image: **Canonical Ubuntu 22.04 (ARM)**
3. Shape: **VM.Standard.A1.Flex** (Always Free Eligible)
4. Networking: asignar IP pública
5. SSH: subir tu llave pública o generar una
6. Repetir 3 veces, cambiar región cada vez (Phoenix → Ashburn → Frankfurt)

### Verificar IPs distintas
```bash
ssh ubuntu@<vm1-ip> "curl ifconfig.me"
ssh ubuntu@<vm2-ip> "curl ifconfig.me"
ssh ubuntu@<vm3-ip> "curl ifconfig.me"
# Las 3 deben dar IPs distintas
```

### Test contra DI desde cada VM
```bash
ssh ubuntu@<vm1-ip>
git clone <repo> && cd re_cl
pip install requests playwright
playwright install chromium
# Subir di_cookies_1.json via scp
py scripts/test_proxy.py --account 1
# Si OK 200 → usar esa VM para cuenta 1
```

### Cron en cada VM
```cron
# Cuenta 1 en VM Phoenix
0 6 * * * cd /home/ubuntu/RE_CL/re_cl && py scripts/run_di_bulk_multi.py 2>&1 | tee -a nightly.log

# Cuenta 2 en VM Ashburn
0 7 * * * cd /home/ubuntu/RE_CL/re_cl && py scripts/run_di_bulk_multi.py 2>&1 | tee -a nightly.log

# Cuenta 3 en VM Frankfurt  
0 8 * * * cd /home/ubuntu/RE_CL/re_cl && py scripts/run_di_bulk_multi.py 2>&1 | tee -a nightly.log
```

Las 3 VMs corren independientemente con 3 IPs y 3 cuentas distintas.

---

*Actualización 2026-05-01 — alternativas gratuitas reales para evitar ProtonVPN/IPRoyal*
