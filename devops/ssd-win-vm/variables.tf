variable "credentials_file" {
  description = "Path to the GCP credentials JSON file"
  type        = string
  sensitive   = true
  # No default value - must be provided in terraform.tfvars
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  # No default value - must be provided in terraform.tfvars
}

variable "region" {
  description = "GCP region/zone"
  type        = string
  # No default value - must be provided in terraform.tfvars
}

variable "disk_name" {
  description = "Name for the SSD disk"
  type        = string
  default     = "geofsm-ssd-disk"
}

variable "disk_type" {
  description = "Type of disk to create"
  type        = string
  default     = "pd-ssd"
}

variable "disk_size" {
  description = "Size of the disk in GB"
  type        = number
  default     = 30
}

variable "instance_name" {
  description = "Name of the VM instance to attach the disk to"
  type        = string
  default     = "windows-vm-geofsm"
}
