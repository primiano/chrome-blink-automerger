# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.


AUTOMERGER_NAME = 'Chromium+Blink automerger'
AUTOMERGER_EMAIL = 'chrome-blink-automerger@chromium.org'

BLINK_REPO_URL = 'https://chromium.googlesource.com/chromium/blink.git'
CHROMIUM_REPO_URL = 'https://chromium.googlesource.com/chromium/src.git'

BRANCHES_TO_MERGE = [
    # Chromium ref,                         Blink ref,                    append_commit_position
    ('refs/heads/master',              'refs/heads/master',               True),
    ('refs/pending/heads/master',      'refs/heads/master',               False),

    ('refs/branch-heads/2454',         'refs/branch-heads/chromium/2454', True),
    ('refs/pending/branch-heads/2454', 'refs/branch-heads/chromium/2454', False),

    ('refs/branch-heads/2490',         'refs/branch-heads/chromium/2490', True),
    ('refs/pending/branch-heads/2490', 'refs/branch-heads/chromium/2490', False),
]

MERGE_MSG = """Merge Chromium + Blink git repositories

Blink SHA1: %(blink_sha)s
Blink revision: %(blink_branch)s@%(blink_rev)s

BUG=431458
"""
