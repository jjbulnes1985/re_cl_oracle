#!/bin/bash
# Oracle Cloud — Setup one-paste
# ===============================
# Pega este script en Oracle Cloud Shell (botón ">_" arriba a la derecha del dashboard).
# Provisiona 3 VMs ARM Always Free en regiones distintas con scraper DI listo.
#
# Tiempo estimado: 8-12 minutos (espera por boot de VMs).
# Costo: USD 0 (Always Free tier).

set -e

REPO_URL="https://github.com/jjbulnes1985/re_cl_oracle.git"
VM_NAMES=("re_cl_di_account1_phx" "re_cl_di_account2_iad" "re_cl_di_account3_fra")
REGIONS=("us-phoenix-1" "us-ashburn-1" "eu-frankfurt-1")

echo "============================================================"
echo "RE_CL — Oracle Cloud one-paste setup"
echo "============================================================"

# Get tenancy + compartment (Cloud Shell sets OCI_TENANCY; fall back to config file)
TENANCY="${OCI_TENANCY:-}"
if [ -z "$TENANCY" ]; then
    TENANCY=$(awk -F'=' '/^tenancy/{gsub(/ /,"",$2); print $2; exit}' ~/.oci/config 2>/dev/null)
fi
if [ -z "$TENANCY" ]; then
    TENANCY=$(oci iam compartment list --include-root --query "data[?\"compartment-id\" == null].id | [0]" --raw-output 2>/dev/null)
fi
if [ -z "$TENANCY" ] || [ "$TENANCY" = "null" ]; then
    echo "ERROR: Could not determine tenancy OCID."
    echo "Try running: oci iam compartment list --include-root --query 'data[?\"compartment-id\" == null].id | [0]' --raw-output"
    exit 1
fi
COMPARTMENT_ID="$TENANCY"
echo "Tenancy/Compartment: $COMPARTMENT_ID"

# Generate SSH key if not exists
if [ ! -f ~/.ssh/id_rsa ]; then
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa -N "" -q
    echo "Generated SSH key at ~/.ssh/id_rsa"
fi
SSH_PUB=$(cat ~/.ssh/id_rsa.pub)

# Cloud-init template (instala todo y arranca cron)
cat > /tmp/cloud-init.yaml <<'CLOUDINIT'
#cloud-config
package_update: true
packages:
  - python3-pip
  - python3-venv
  - git
  - postgresql-client
  - curl
runcmd:
  - su - ubuntu -c "git clone REPO_URL_PLACEHOLDER /home/ubuntu/RE_CL"
  - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && python3 -m venv .venv"
  - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && .venv/bin/pip install --upgrade pip"
  - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && .venv/bin/pip install -r requirements.txt"
  - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && .venv/bin/playwright install --with-deps chromium"
  - su - ubuntu -c "mkdir -p /home/ubuntu/RE_CL/re_cl/data/processed /home/ubuntu/RE_CL/re_cl/data/logs"
  - echo "0 6 * * * cd /home/ubuntu/RE_CL/re_cl && /home/ubuntu/RE_CL/re_cl/.venv/bin/python scripts/run_di_bulk_multi.py >> /home/ubuntu/RE_CL/re_cl/data/logs/oracle_nightly.log 2>&1" | crontab -u ubuntu -
  - echo "[$(date)] VM ready" > /home/ubuntu/setup_complete.flag
CLOUDINIT
sed -i "s|REPO_URL_PLACEHOLDER|$REPO_URL|g" /tmp/cloud-init.yaml
CLOUD_INIT_B64=$(base64 -w 0 /tmp/cloud-init.yaml)

# Create VCN + subnet + IGW for each region (or reuse Default)
echo ""
echo "Provisioning 3 VMs (ARM Ampere A1.Flex, 1 OCPU + 6GB RAM each)..."
echo ""

# For each region, create VM
for i in "${!REGIONS[@]}"; do
    REGION="${REGIONS[$i]}"
    NAME="${VM_NAMES[$i]}"
    echo "[$REGION] Provisioning $NAME..."

    # Find available image (Ubuntu 22.04 ARM)
    IMAGE_ID=$(oci compute image list \
        --compartment-id "$COMPARTMENT_ID" \
        --region "$REGION" \
        --operating-system "Canonical Ubuntu" \
        --operating-system-version "22.04" \
        --shape "VM.Standard.A1.Flex" \
        --sort-by "TIMECREATED" --sort-order "DESC" \
        --query "data[0].id" --raw-output)

    AD=$(oci iam availability-domain list \
        --region "$REGION" \
        --compartment-id "$COMPARTMENT_ID" \
        --query "data[0].name" --raw-output)

    # Use default VCN/subnet if exists, else create
    SUBNET_ID=$(oci network subnet list \
        --compartment-id "$COMPARTMENT_ID" \
        --region "$REGION" \
        --query "data[0].id" --raw-output 2>/dev/null) || SUBNET_ID=""

    if [ -z "$SUBNET_ID" ] || [ "$SUBNET_ID" = "null" ]; then
        echo "  Creating VCN + subnet..."
        VCN_ID=$(oci network vcn create \
            --compartment-id "$COMPARTMENT_ID" \
            --region "$REGION" \
            --cidr-block "10.0.0.0/16" \
            --display-name "re_cl_vcn_$i" \
            --query "data.id" --raw-output)
        SUBNET_ID=$(oci network subnet create \
            --compartment-id "$COMPARTMENT_ID" \
            --region "$REGION" \
            --vcn-id "$VCN_ID" \
            --cidr-block "10.0.1.0/24" \
            --display-name "re_cl_subnet_$i" \
            --query "data.id" --raw-output)
        IGW_ID=$(oci network internet-gateway create \
            --compartment-id "$COMPARTMENT_ID" \
            --region "$REGION" \
            --vcn-id "$VCN_ID" \
            --is-enabled true \
            --display-name "re_cl_igw_$i" \
            --query "data.id" --raw-output)
    fi

    # Launch instance
    INSTANCE_ID=$(oci compute instance launch \
        --availability-domain "$AD" \
        --compartment-id "$COMPARTMENT_ID" \
        --region "$REGION" \
        --shape "VM.Standard.A1.Flex" \
        --shape-config '{"ocpus": 1, "memoryInGBs": 6}' \
        --image-id "$IMAGE_ID" \
        --subnet-id "$SUBNET_ID" \
        --display-name "$NAME" \
        --metadata "{\"ssh_authorized_keys\": \"$SSH_PUB\", \"user_data\": \"$CLOUD_INIT_B64\"}" \
        --assign-public-ip true \
        --query "data.id" --raw-output)

    echo "  Created: $INSTANCE_ID"
done

echo ""
echo "============================================================"
echo "All 3 VMs provisioned. Waiting for boot + cloud-init (~5 min)..."
echo "============================================================"
sleep 120

echo ""
echo "Public IPs of your VMs:"
for REGION in "${REGIONS[@]}"; do
    oci compute instance list \
        --compartment-id "$COMPARTMENT_ID" \
        --region "$REGION" \
        --query "data[?contains(\"display-name\", 're_cl_di')].{name:\"display-name\", state:\"lifecycle-state\"}" \
        --output table
    # Public IP
    INSTANCE_OCID=$(oci compute instance list --compartment-id "$COMPARTMENT_ID" --region "$REGION" --query "data[0].id" --raw-output 2>/dev/null)
    if [ -n "$INSTANCE_OCID" ]; then
        IP=$(oci compute instance list-vnics --instance-id "$INSTANCE_OCID" --region "$REGION" --query "data[0].\"public-ip\"" --raw-output 2>/dev/null)
        echo "  [$REGION] $IP"
    fi
done

echo ""
echo "============================================================"
echo "NEXT STEPS (manual):"
echo "  1. SSH a cada VM:  ssh ubuntu@<ip>"
echo "  2. Subir cookies:  scp data/processed/datainmobiliaria_cookies.json ubuntu@<vm1>:~/RE_CL/re_cl/data/processed/"
echo "                     scp data/processed/di_cookies_2.json ubuntu@<vm2>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json"
echo "                     scp data/processed/di_cookies_3.json ubuntu@<vm3>:~/RE_CL/re_cl/data/processed/datainmobiliaria_cookies.json"
echo "  3. Cada noche 06:00 UTC cada VM scrapea con su cuenta + IP propia"
echo "============================================================"
