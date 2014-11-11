#!/bin/bash
# Invoke this script with --project google-cloud-project-name as args.

source "$(dirname $0)/vars.sh"

if [ -f "$(dirname $0)/netrc" ]; then
  NETRC_META="netrc=$(dirname $0)/netrc"
fi

GC_ZONE="us-central1-f"
PERSISTENT_DISK="chromium-blink-automerger-ssd"

# Create the persistent disk if not existing
gcloud compute disks describe "${PERSISTENT_DISK}" \
    --zone "${GC_ZONE}" -q "$@" &>/dev/null
[ $? -eq 0 ] || {
  gcloud compute disks create "chromium-blink-automerger-ssd" \
      --size "32" --zone "${GC_ZONE}" --type "pd-ssd" "$@"
}

gcloud compute \
    instances create "chromium-bink-automerger" \
    --machine-type "g1-small" \
    --metadata-from-file startup-script=startup_script.sh "${NETRC_META}"\
    --metadata AUTOMERGER_REPO="${AUTOMERGER_REPO}" \
               AUTOMERGER_BRANCH="${AUTOMERGER_BRANCH}" \
    --zone "${GC_ZONE}" \
    --network "default" \
    --maintenance-policy "MIGRATE" \
    --scopes "https://www.googleapis.com/auth/devstorage.read_only" \
    --tags "http-server" "https-server" \
    --image "https://www.googleapis.com/compute/v1/projects/gce-nvme/global/images/nvme-backports-debian-7-wheezy-v20140904" \
    --boot-disk-size 40GB \
    --disk name=${PERSISTENT_DISK} \
           device-name=${PERSISTENT_DISK} \
           auto-delete=no  \
    "$@"

gcloud compute firewall-rules create allow-http --description "http" \
    --allow tcp:80,8080,443 "$@" &>/dev/null