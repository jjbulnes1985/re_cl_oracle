# Oracle Cloud — Guía paso a paso (3 VMs Always Free)

**Objetivo:** Levantar 3 VMs Oracle Cloud (Phoenix, Ashburn, Frankfurt) para scrapear DataInmobiliaria desde 3 IPs distintas en paralelo, ganando 3× throughput sobre el scraper local.

**Costo:** USD 0/mes — Always Free tier (4 OCPU + 24GB RAM ARM Ampere, 200GB block storage).
**Tiempo estimado:** 30 min de tu tiempo + 60 min de provisioning automático.

---

## Lo que tú tienes que hacer manualmente

Estos pasos **requieren tu acción humana** (KYC, login, decisiones de billing). No los puedo hacer por ti.

### Paso 1 — Crear cuenta Oracle Cloud (10 min)

1. Ve a **https://signup.oraclecloud.com/**
2. Completa el formulario:
   - Email: `jjbulnes@gmail.com`
   - País/territorio: **Chile**
   - Nombre, apellido
3. Verifica el email — Oracle te manda código.
4. **Información de pagos** (Always Free igual exige tarjeta para verificación de identidad):
   - Tarjeta de crédito (no debita nada — solo $1 USD pre-auth que se devuelve)
   - **NO** tarjeta de débito de bancos chilenos (Banco Estado/BCI a veces fallan). Recomendado: Visa/Mastercard internacional o Amex.
5. **Home region:** elige **US East (Ashburn)** — más cuotas Always Free disponibles.
6. Acepta términos → Click "Start my free trial"
7. **Espera 5-15 min** mientras Oracle aprovisiona tu tenancy. Recibirás email de confirmación.

> ⚠️ **Si te rechaza la tarjeta:** intenta con otra tarjeta o usa una tarjeta virtual (Mercado Pago, RappiCash). Es el bloqueante más común.

---

### Paso 2 — Login y verificación inicial (2 min)

1. Login en **https://cloud.oracle.com/** con el email registrado.
2. En la barra superior, anota:
   - **Tenancy name** (esquina superior derecha bajo tu avatar)
   - **Home region** (debe decir "US East (Ashburn) - us-ashburn-1")
3. Verifica que apareces como **"Always Free"** en la sección "Account Details".

---

### Paso 3 — Subir tu repo a GitHub público (5 min, opcional pero recomendado)

Las VMs necesitan clonar tu repo para correr el scraper. Si tu repo ya es público en GitHub, salta este paso.

**Opción A — Tu repo ya es público:**
- Anota la URL: `https://github.com/USUARIO/REPO.git`

**Opción B — Tu repo es privado:** crea un fork público sólo con `re_cl/` (sin datos sensibles):
```bash
# Desde tu máquina local (cmd):
cd "c:/Users/jjbul/Dropbox/Trabajos (Material)/JJB/IA/Juan Montes/RE_CL"
git remote add public https://github.com/jjbulnes/re_cl_oracle.git  # crea repo en gh primero
git push public master
```

> **Importante:** NO subas las cookies (`data/processed/datainmobiliaria_cookies.json`, `di_cookies_2.json`, `di_cookies_3.json`). El `.gitignore` ya las excluye, pero verifica con `git status` antes de pushear.

---

### Paso 4 — Abrir Cloud Shell (1 min)

Esto es el botón que dispara mi script automatizado.

1. En el dashboard de Oracle Cloud (cloud.oracle.com), arriba a la derecha vas a ver un ícono **`>_`** (consola).
2. Click — abre una terminal Linux dentro de tu navegador, ya autenticada con tu cuenta Oracle.
3. Espera 30s a que cargue completamente.

---

### Paso 5 — Pegar el script de provisioning (15 min)

1. **En tu máquina local**, abre `re_cl/infra/oracle_cloud/oracle_one_paste.sh` en un editor.
2. **Edita la línea 12**:
   ```bash
   REPO_URL="https://github.com/USUARIO/REPO.git"   # ← reemplaza con tu URL del Paso 3
   ```
3. **Selecciona TODO el contenido** del script (Ctrl+A, Ctrl+C).
4. **Pega** (Ctrl+Shift+V) en la Cloud Shell del navegador y presiona Enter.
5. El script hace **automáticamente**:
   - Genera SSH key si no existe (`~/.ssh/id_rsa`)
   - Crea VCN + subnet + Internet Gateway en cada región
   - Aprovisiona 3 VMs ARM (1 OCPU + 6GB RAM cada una) en Phoenix, Ashburn, Frankfurt
   - Instala cloud-init: Python 3.11, git, Playwright, dependencias, clona tu repo
   - Configura cron diario a las 06:00 UTC para correr `run_di_bulk_multi.py`
6. **Espera 8-12 minutos** mientras se aprovisiona. El script muestra "All 3 VMs provisioned" y los IPs públicos.

> ⚠️ **Si falla con "LimitExceeded":** tu cuenta no tiene capacidad ARM Always Free en esa región. Reintenta cambiando 1-2 regiones en el array `REGIONS=(...)` por opciones en el orden Frankfurt → Phoenix → Ashburn → Sao Paulo → São Paulo → Tokyo.

---

### Paso 6 — Subir cookies a cada VM (5 min)

Cada VM debe tener un archivo de cookies distinto (una cuenta DI por VM).

**Desde tu máquina local** (cmd o PowerShell):

```bash
cd "c:/Users/jjbul/Dropbox/Trabajos (Material)/JJB/IA/Juan Montes/RE_CL/re_cl"

# Reemplaza <IP_VM1>, <IP_VM2>, <IP_VM3> con los que mostró el script de Oracle (Paso 5)
scp -i ~/.ssh/id_rsa data/processed/datainmobiliaria_cookies.json ubuntu@<IP_VM1>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json

scp -i ~/.ssh/id_rsa data/processed/di_cookies_2.json ubuntu@<IP_VM2>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json

scp -i ~/.ssh/id_rsa data/processed/di_cookies_3.json ubuntu@<IP_VM3>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json
```

> **Nota:** Cada VM recibe el cookie file con el nombre **estándar** `datainmobiliaria_cookies.json` (no `di_cookies_2.json`). Es porque el scraper en cada VM usa una sola cuenta — no rotación interna.

---

### Paso 7 — Verificar que cron funciona (3 min)

SSH a cada VM y prueba manualmente:

```bash
ssh -i ~/.ssh/id_rsa ubuntu@<IP_VM1>

# Dentro de la VM:
cd ~/RE_CL/re_cl
source .venv/bin/activate
python scripts/run_di_bulk_multi.py --max-comunas 1 --dry-run

# Si devuelve "OK" + 1 comuna identificada → cron funciona
exit
```

Repite para VM2 y VM3.

---

### Paso 8 — Bajar resultados de cada VM (rutina diaria)

Cada noche a las 06:00 UTC (03:00 Chile invierno / 02:00 Chile verano), las 3 VMs scrapen automáticamente cada una con su IP propia + cuenta propia. Mañana siguiente:

```bash
# Desde tu máquina local — script para bajar todo a tu DB:
cd "c:/Users/jjbul/Dropbox/Trabajos (Material)/JJB/IA/Juan Montes/RE_CL/re_cl"

for vm in <IP_VM1> <IP_VM2> <IP_VM3>; do
  scp -i ~/.ssh/id_rsa ubuntu@$vm:~/RE_CL/re_cl/data/processed/datainmobiliaria_*.csv data/processed/oracle_$vm/
done

# Luego corre el pipeline local con los CSV bajados:
py src/ingestion/load_transactions.py --source data_inmobiliaria_oracle
py src/ingestion/clean_transactions.py
py src/features/build_features.py --skip-ieut
py src/scoring/opportunity_score.py
```

> **Mejora futura:** podemos automatizar el download diario con otro cron en tu PC (`scripts/oracle_daily_pull.bat`), o mejor: configurar las VMs para hacer push a un bucket Oracle Object Storage Always Free (10GB gratis).

---

## Throughput esperado

| Setup | Comunas/día | Tiempo total para 13 restantes |
|-------|-------------|-------------------------------|
| Local (1 IP, 3 cuentas) | ~2-3 con WARP | ~5-7 días |
| Oracle Cloud (3 VMs, 3 IPs distintas) | ~9-12 | **~1-2 días** |

Cada VM scrape ~3-4 comunas/día con su propia quota DI (cuota es por IP + cuenta). 3 VMs × 3-4 = 9-12 comunas/día. Las 13 comunas pendientes se completan en 1-2 días.

---

## Troubleshooting

### "Out of host capacity"
La región eligida no tiene VMs ARM Always Free libres. Cambia la región en `oracle_one_paste.sh` línea 14:
```bash
REGIONS=("us-phoenix-1" "us-ashburn-1" "eu-frankfurt-1")
# ↓ alternativas si fallan ↓
REGIONS=("sa-saopaulo-1" "ap-tokyo-1" "uk-london-1")
```

### Las VMs no responden a SSH
Verifica que el Security List de tu VCN permite tráfico TCP entrante en puerto 22:
```bash
oci network security-list update --security-list-id <SL_OCID> \
  --ingress-security-rules '[{"source":"0.0.0.0/0","protocol":"6","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}}]'
```
O hazlo manualmente en el dashboard: VCN > Security Lists > Default Security List > Add Ingress Rule (0.0.0.0/0, TCP 22).

### Cron no se ejecuta
SSH a la VM y revisa:
```bash
ssh ubuntu@<IP> "crontab -l"               # debe mostrar la línea de las 06:00
ssh ubuntu@<IP> "tail -50 ~/RE_CL/re_cl/data/logs/oracle_nightly.log"
ssh ubuntu@<IP> "sudo systemctl status cron"
```

### La VM se quedó sin memoria
ARM Ampere 6GB es ajustado para Playwright + Chromium. Si crashea:
```bash
# En la VM:
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## Resumen visual

```
┌─────────────────────────────────────────────────────────────┐
│ TÚ (5 pasos manuales, 30 min total)                        │
├─────────────────────────────────────────────────────────────┤
│ 1. Crear cuenta Oracle (signup.oraclecloud.com) — 10 min  │
│ 2. Login dashboard (cloud.oracle.com) — 2 min             │
│ 3. Subir repo a GitHub público — 5 min                    │
│ 4. Abrir Cloud Shell (botón >_) — 1 min                   │
│ 5. Pegar oracle_one_paste.sh editado — 1 min              │
│                                                            │
│ → ESPERAR 8-12 min (provisioning automático)              │
│                                                            │
│ 6. SCP cookies a cada VM — 5 min                          │
│ 7. Verificar cron en cada VM — 3 min                      │
│ 8. Bajar CSV diario (mañana siguiente) — automatizable    │
└─────────────────────────────────────────────────────────────┘

      ↓ luego ↓

┌─────────────────────────────────────────────────────────────┐
│ AUTOMÁTICO (cada noche, sin intervención)                  │
├─────────────────────────────────────────────────────────────┤
│ 06:00 UTC → 3 VMs scrapen en paralelo (cada una con IP+cta│
│ 12:00 UTC → tú bajas CSV con scripts/oracle_daily_pull.bat│
│ 13:00 → pipeline local actualiza candidates + scoring     │
└─────────────────────────────────────────────────────────────┘
```

---

## Archivos relacionados

- `oracle_one_paste.sh` — Script bash que pegas en Cloud Shell
- `main.tf` — Versión Terraform (alternativa para infra-as-code)
- `prompts/vpn_free_alternatives.md` — Otras opciones gratis (tethering, café WiFi, reset módem)
