variable "credentials_file" {
  description = "Path to the GCP credentials JSON file"
  type        = string
  sensitive   = true
  # No default value - must be provided in terraform.tfvars (which is gitignored)
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  # No default value - must be provided in terraform.tfvars (which is gitignored)
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1-a"
}

variable "vm_name" {
  description = "Name of the Windows VM instance"
  type        = string
  default     = "windows-vm-geofsm"
}

variable "machine_type" {
  description = "Machine type for the VM"
  type        = string
  default     = "n1-standard-2"
}

variable "windows_image" {
  description = "Windows Server image to use"
  type        = string
  default     = "windows-server-2016-dc-v20240516"
}

variable "network" {
  description = "Network for VM"
  type        = string
  default     = "default"
}

variable "tags" {
  description = "Network tags for the VM"
  type        = list(string)
  default     = ["ftp"]
}

variable "ftp_source_ranges" {
  description = "Source IP ranges for FTP access"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}
