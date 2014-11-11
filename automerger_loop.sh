#!/bin/bash
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

source "$(dirname $0)/vars.sh"

touch automerger.log
touch automerger-full.log
chmod 644 automerger.log automerger-full.log

while true; do
  echo 
  echo "Starting automerger cycle $(date)"

  # Self-update
  git -C "$(dirname $0)" pull --ff-only
  git -C "$(dirname $0)" clean -df
  pkill git

  cat automerger.log >> automerger-full.log
  tail -n 10000 automerger-full.log > automerger-full.log.tmp
  mv -f automerger-full.log.tmp automerger-full.log
  date > automerger.log
  "$(dirname $0)/automerger_iteration.sh" &>> automerger.log
  exit_code=$?
  echo "---END exit_code=${exit_code}  $(date)" >> automerger.log

  if [ $exit_code != 0 ]; then
    echo "Automerger error (exit_code: $exit_code)"
  fi
  echo "Automerger cycle ended $(date)"
  sleep ${AUTOMERGER_CYCLE_TIME_SEC}
done