#!/bin/bash
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

source "$(dirname $0)/vars.sh"

touch automerger.log
touch automerger-full.log
chmod 644 automerger.log automerger-full.log

getdate() {
  echo "$(date --utc)  [$(TZ='America/Los_Angeles' date +'%H:%M %Z')]"
}

while true; do
  echo 
  echo "Starting automerger cycle $(getdate)"

  # Self-update
  pkill -u "${USER}" git
  git -C "$(dirname $0)" pull --ff-only
  git -C "$(dirname $0)" clean -df

  cat automerger.log >> automerger-full.log
  tail -n 10000 automerger-full.log > automerger-full.log.tmp
  mv -f automerger-full.log.tmp automerger-full.log
  getdate > automerger.log
  "$(dirname $0)/automerger_iteration.sh" &>> automerger.log
  exit_code=$?
  /bin/echo -e "\n --- --- exit_code=${exit_code} $(getdate) --- ---\n\n" \
      >> automerger.log

  if [ $exit_code != 0 ]; then
    echo "Automerger error. Exit_code=${exit_code} $(getdate)"
  else
    echo "Automerger cycled successfully $(getdate)"
  fi
  sleep ${AUTOMERGER_CYCLE_TIME_SEC}
done