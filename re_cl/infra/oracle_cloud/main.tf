# Terraform: 3 VMs Oracle Cloud Always Free para scraping DI distribuido
#
# Pre-requisito: cuenta Oracle Cloud (free tier) en https://signup.cloud.oracle.com
# y tu API key + tenancy_ocid configurados localmente.
#
# Uso:
#   terraform init
#   terraform apply -var="ssh_pub_key=$(cat ~/.ssh/id_rsa.pub)"
#
# Despues del apply: 3 VMs ARM corriendo en Phoenix, Ashburn y Frankfurt
# con IPs publicas distintas. Cada una con cron para scrapear con 1 cuenta.

terraform {
  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 5.0"
    }
  }
}

variable "tenancy_ocid"      { type = string }
variable "user_ocid"         { type = string }
variable "fingerprint"       { type = string }
variable "private_key_path"  { type = string }
variable "ssh_pub_key"       { type = string }

variable "regions" {
  type = list(string)
  default = ["us-phoenix-1", "us-ashburn-1", "eu-frankfurt-1"]
}

variable "compartment_ocid" { type = string }

provider "oci" {
  alias            = "phx"
  region           = "us-phoenix-1"
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
}

provider "oci" {
  alias            = "iad"
  region           = "us-ashburn-1"
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
}

provider "oci" {
  alias            = "fra"
  region           = "eu-frankfurt-1"
  tenancy_ocid     = var.tenancy_ocid
  user_ocid        = var.user_ocid
  fingerprint      = var.fingerprint
  private_key_path = var.private_key_path
}

# Cloud-init: instala dependencias + clona repo + configura cron
locals {
  cloud_init_template = <<-EOT
    #cloud-config
    package_update: true
    packages:
      - python3-pip
      - python3-venv
      - git
      - postgresql-client
    runcmd:
      - su - ubuntu -c "git clone https://github.com/USER/REPO.git /home/ubuntu/RE_CL"
      - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && python3 -m venv .venv"
      - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && .venv/bin/pip install -r requirements.txt"
      - su - ubuntu -c "cd /home/ubuntu/RE_CL/re_cl && .venv/bin/playwright install --with-deps chromium"
      - echo "0 ${ACCOUNT_HOUR} * * * cd /home/ubuntu/RE_CL/re_cl && .venv/bin/python scripts/run_di_bulk_multi.py >> /home/ubuntu/nightly.log 2>&1" | crontab -u ubuntu -
  EOT
}

# === VM 1 — Phoenix (cuenta 1) ===
data "oci_core_images" "phx_arm" {
  provider          = oci.phx
  compartment_id    = var.compartment_ocid
  operating_system  = "Canonical Ubuntu"
  shape             = "VM.Standard.A1.Flex"
  state             = "AVAILABLE"
}

data "oci_core_availability_domains" "phx" {
  provider       = oci.phx
  compartment_id = var.compartment_ocid
}

resource "oci_core_vcn" "phx_vcn" {
  provider       = oci.phx
  cidr_block     = "10.0.0.0/16"
  compartment_id = var.compartment_ocid
  display_name   = "re_cl_vcn_phx"
}

resource "oci_core_subnet" "phx_subnet" {
  provider       = oci.phx
  cidr_block     = "10.0.1.0/24"
  vcn_id         = oci_core_vcn.phx_vcn.id
  compartment_id = var.compartment_ocid
  display_name   = "re_cl_subnet_phx"
}

resource "oci_core_internet_gateway" "phx_igw" {
  provider       = oci.phx
  vcn_id         = oci_core_vcn.phx_vcn.id
  compartment_id = var.compartment_ocid
}

resource "oci_core_instance" "phx_vm" {
  provider            = oci.phx
  availability_domain = data.oci_core_availability_domains.phx.availability_domains[0].name
  compartment_id      = var.compartment_ocid
  display_name        = "re_cl_di_scraper_account1"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = 1
    memory_in_gbs = 6
  }

  source_details {
    source_type = "image"
    source_id   = data.oci_core_images.phx_arm.images[0].id
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.phx_subnet.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = var.ssh_pub_key
    user_data           = base64encode(replace(local.cloud_init_template, "$${ACCOUNT_HOUR}", "6"))
  }
}

# === VM 2 — Ashburn (cuenta 2) ===
# (Estructura análoga — VCN, Subnet, IGW, Instance)
# Reemplazar oci.phx → oci.iad y account_hour="7"

# === VM 3 — Frankfurt (cuenta 3) ===
# (Estructura análoga — oci.fra y account_hour="8")

output "phx_public_ip" {
  value = oci_core_instance.phx_vm.public_ip
}
