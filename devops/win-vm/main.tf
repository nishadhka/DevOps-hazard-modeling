provider "google" {
  credentials = file(var.credentials_file)
  project     = var.project_id
  region      = var.region
}

#resource "google_compute_disk" "windows_data_disk" {
#  name  = "windows-data-disk"
#  type  = "pd-ssd"  # You can use "pd-standard" for standard persistent disk
#  zone  = var.region  # Using the same region/zone as defined in variables
#  size  = 30  # Size in GB
#}

resource "google_compute_instance" "windows_instance" {
  name         = var.vm_name
  machine_type = var.machine_type
  zone         = var.region

  boot_disk {
    initialize_params {
      image = var.windows_image
    }
  }

  network_interface {
    network = var.network
    access_config {
      // Ephemeral IP
    }
  }

  tags = var.tags

  metadata = {
    windows-startup-script-ps1 = <<-EOF
      Install-WindowsFeature -Name Web-FTP-Server -IncludeAllSubFeature
      Start-Service -Name ftpsvc
    EOF
  }

#  attached_disk {
#    source      = google_compute_disk.windows_data_disk.id
#    device_name = "windows-data-disk"
# }
#  depends_on = [google_compute_disk.windows_data_disk]
}

resource "google_compute_firewall" "allow_ftp" {
  name    = "allow-ftp"
  network = var.network

  allow {
    protocol = "tcp"
    ports    = ["21"]
  }

  source_ranges = var.ftp_source_ranges

  target_tags = var.tags
}
