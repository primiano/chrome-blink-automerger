#!/bin/bash
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

source "$(dirname $0)/vars.sh"

while true; do
  echo 
  echo "Starting automerger cycle $(date)"

  # Self-update
  git -C "$(dirname $0)" pull --ff-only
  git -C "$(dirname $0)" clean -df

  "$(dirname $0)/automerger_iteration.sh"
  exit_code=$?
  if [ $exit_code != 0 ]; then
    echo "Automerger error (exit_code: $exit_code)"
  fi
  echo "Automerger cycle ended $(date)"
  sleep ${AUTOMERGER_CYCLE_TIME_SEC}
done