# Fórmula automática para completar las 30 comunas DI

> **Setup once, run forever.** Una vez configurado, el sistema scrapea solo cada noche
> usando 3 IPs distintas + 3 cuentas → ~45k rows/día → 30 comunas en ~7 días.

---

## Opción A — La fórmula más simple (PC + Cloudflare WARP)

### Setup en 5 minutos

1. Bajar **Cloudflare WARP** (gratis, sin cuenta requerida) en https://1.1.1.1
2. Instalar y dejar instalado (NO conectar todavía)
3. Verificar que `warp-cli` esté en PATH:
   ```bash
   warp-cli --version
   ```
4. Listo.

### Cómo se usa
**Reemplazar el cron** del Task Scheduler para que llame a `run_di_auto.py` en vez de `run_di_bulk_multi.py`:

```bat
@echo off
cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"
echo [%date% %time%] DI auto-rotate start >> data\logs\di_auto_nightly.log
py scripts\run_di_auto.py >> data\logs\di_auto_nightly.log 2>&1
echo [%date% %time%] Done >> data\logs\di_auto_nightly.log
```

### Qué hace cada noche a las 06:00
1. Detecta IP actual
2. Prueba quota con cada una de las 3 cuentas
3. Si alguna tiene quota → scrapea con esa
4. Cuando todas se agotan → activa Cloudflare WARP automáticamente
5. Re-prueba cuotas con nueva IP
6. Si WARP también agotada → loguea sugerencia (tethering / reset módem) y termina
7. Te deja un log con todo lo que pasó

### Realista: ¿cuánto scrapea?
- **Sin WARP**: ~15k rows/día (1 IP, agotada al rato)
- **Con WARP funcionando**: ~30-45k rows/día (2 IPs)
- **Si DI bloquea WARP** (datacenter): vuelve a ~15k
- **Para completar 30 comunas**: 7-15 días según efectividad de WARP

---

## Opción B — La fórmula automatizada al 100% (Oracle Cloud)

### Setup en 60 minutos (una sola vez, después es 100% automático)

**Pre-requisitos:** cuenta Oracle Cloud (signup gratis, requiere tarjeta solo para verificación, **no cobra nada**).

### Paso 1: Cuenta Oracle Cloud

1. Ir a https://signup.cloud.oracle.com
2. Rellenar formulario, esperar email de activación (~10 min)
3. Login → Console
4. Crear API key:
   - Menu → User Settings → API Keys → Add API Key → Generate
   - Descargar la `private key` (.pem)
   - Copiar el `tenancy_ocid`, `user_ocid`, `fingerprint`

### Paso 2: Instalar Terraform

```bash
# Windows con Chocolatey
choco install terraform

# O bajar manual desde https://www.terraform.io/downloads
```

### Paso 3: Provisionar las 3 VMs

```bash
cd re_cl/infra/oracle_cloud

# Configurar credenciales en terraform.tfvars
cat > terraform.tfvars <<EOF
tenancy_ocid      = "ocid1.tenancy.oc1..xxx"
user_ocid         = "ocid1.user.oc1..xxx"
fingerprint       = "aa:bb:cc:..."
private_key_path  = "C:/Users/jjbul/.oci/oci_api_key.pem"
ssh_pub_key       = "ssh-rsa AAAAB3..."
compartment_ocid  = "ocid1.tenancy.oc1..xxx"
EOF

terraform init
terraform apply
```

Output: 3 IPs públicas distintas (Phoenix US + Ashburn US + Frankfurt EU).

### Paso 4: Subir cookies a cada VM

```bash
scp data/processed/datainmobiliaria_cookies.json ubuntu@<phx_ip>:~/RE_CL/re_cl/data/processed/
scp data/processed/di_cookies_2.json ubuntu@<iad_ip>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json
scp data/processed/di_cookies_3.json ubuntu@<fra_ip>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json
```

### Paso 5: Configurar sync de checkpoint

Las 3 VMs deben sincronizar el `checkpoint.json` para no scrapear comunas duplicadas. Opciones:
- **Git** (más simple): cada VM hace `git pull` antes y `git commit + push` después
- **S3** (más profesional): AWS S3 free tier o Oracle Object Storage

### Paso 6: Listo — checkear logs

```bash
ssh ubuntu@<phx_ip> "tail -50 ~/nightly.log"
```

Cada noche cada VM scrapea 1 cuenta con 1 IP → 3 sesiones en paralelo cada noche → ~45k rows/día sostenido → 30 comunas en **~7 días**.

---

## Opción C — La fórmula híbrida (lo más rápido)

Combinar A+B+manual:

| Día | Lugar | Método | Comunas |
|-----|-------|--------|---------|
| 1   | Casa | run_di_auto + WARP | 4 |
| 2   | Café | run_di_bulk con WiFi del lugar | 5 |
| 3   | Casa + cel | tethering + run_di_auto | 5 |
| 4   | Casa | run_di_auto + reset módem | 3 |
| 5   | Casa | Oracle Cloud activa | 4 |
| 6-7 | Oracle | 24/7 automático | 9 |

**Total: 30 comunas en 7 días, costo USD 0.**

---

## La fórmula automática mínima (TL;DR)

Si solo quieres **una cosa que corra automáticamente sin tu intervención**:

```bash
# 1. Bajar Cloudflare WARP gratis en https://1.1.1.1
# 2. Reemplazar el .bat del Task Scheduler:

# Edit: C:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl\scripts\run_datainmobiliaria_nightly.bat

@echo off
cd /d "c:\Users\jjbul\Dropbox\Trabajos (Material)\JJB\IA\Juan Montes\RE_CL\re_cl"
py scripts\run_di_auto.py >> data\logs\di_auto.log 2>&1
```

Y listo. Cada noche a las 06:00 el sistema:
1. Prueba quotas
2. Scrape con cuenta disponible
3. Si todas agotadas → activa WARP → re-intenta
4. Logea todo en `data/logs/di_auto.log`

---

## Checklist activación (15 minutos)

```
[ ] Bajar Cloudflare WARP de https://1.1.1.1
[ ] Instalar (next, next, finish)
[ ] Verificar warp-cli en cmd: warp-cli --version
[ ] Editar run_datainmobiliaria_nightly.bat para llamar a run_di_auto.py
[ ] Probar manual: cd re_cl && py scripts/run_di_auto.py --check-only
[ ] Mañana 06:00 AM revisar data/logs/di_auto.log
```

Si en 3 días no avanzan las comunas → switchear a Opción B (Oracle Cloud).

---

*Fórmula creada 2026-05-01 — para escenario "no quiero pagar nada y que sea automático"*
