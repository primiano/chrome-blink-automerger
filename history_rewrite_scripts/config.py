# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


AUTOMERGER_NAME = 'Chromium+Blink automerger'
AUTOMERGER_EMAIL = 'chrome-blink-automerger@chromium.org'

BLINK_REPO_URL = 'https://chromium.googlesource.com/chromium/blink.git'
CHROMIUM_REPO_URL = 'https://chromium.googlesource.com/chromium/src.git'

# 'ref/in/chromium' -> 'ref/in/blink'
BRANCHES_TO_MERGE = [
    ('refs/heads/master', 'refs/heads/master'),
    ('refs/branch-heads/2403', 'refs/branch-heads/chromium/2403'),
    ('refs/branch-heads/2454', 'refs/branch-heads/chromium/2454'),
    ('refs/branch-heads/2490', 'refs/branch-heads/chromium/2490'),
]

MERGE_MSG = """Merge Chromium + Blink git repositories

Chromium SHA1: %(chromium_sha)s
Chromium position: %(chromium_branch)s@{#%(chromium_pos)s}
Blink SHA1: %(blink_sha)s
Blink revision: %(blink_branch)s@%(blink_rev)s

BUG=431458

Cr-Commit-Position: %(chromium_branch)s@{#%(chromium_next_pos)s}
"""
