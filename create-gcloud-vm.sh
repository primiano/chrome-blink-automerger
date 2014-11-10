#!/bin/bash

source "$(dirname $0)/vars.sh"

if [ -f "$(dirname $0)/netrc" ]; then
  NETRC_META="netrc=$(dirname $0)/netrc"
fi

gcloud compute \
    instances create "chrome-bink-automerger" \
    --machine-type "f1-micro" \
    --metadata-from-file startup-script=startup_script.sh "${NETRC_META}"\
    --metadata AUTOMERGER_REPO="${AUTOMERGER_REPO}" \
               AUTOMERGER_BRANCH="${AUTOMERGER_BRANCH}" \
    --zone "us-central1-f" \
    --network "default" \
    --maintenance-policy "MIGRATE" \
    --scopes "https://www.googleapis.com/auth/devstorage.read_only" \
    --tags "http-server" "https-server" \
    --image "https://www.googleapis.com/compute/v1/projects/gce-nvme/global/images/nvme-backports-debian-7-wheezy-v20140904" \
    --boot-disk-size 40GB \
    "$@"

gcloud compute firewall-rules create allow-http --description "http" \
    --allow tcp:80,8080,443 "$@" 2>/dev/null