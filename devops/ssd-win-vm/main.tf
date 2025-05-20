provider "google" {
  credentials = file(var.credentials_file)
  project     = var.project_id
  region      = var.region
}

resource "google_compute_disk" "ssd_disk" {
  name    = var.disk_name
  type    = var.disk_type
  zone    = var.region
  size    = var.disk_size
}

resource "google_compute_attached_disk" "attach_ssd" {
  disk     = google_compute_disk.ssd_disk.id
  instance = var.instance_name
  zone     = var.region
}

output "ssd_disk_id" {
  value       = google_compute_disk.ssd_disk.id
  description = "The ID of the created SSD disk"
}
