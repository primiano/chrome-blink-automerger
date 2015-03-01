#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Remove Blink references from the gclient DEPS file contents."""

import ast
import re
import sys


def CleanupDeps(deps):
  assert ast.parse(deps), 'DEPS (original) smoke test (AST parsing) failed'

  # remove webkit_* vars
  deps = re.sub(r"['\"]webkit_\w+['\"]:[^,]+,(?:\s*\#.*)?\s*", '', deps, re.MULTILINE)

  # remove the third_party/WebKit DEPS entry.
  deps = re.sub(r"['\"]src/third_party/WebKit['\"]:[^,]+,\s*", '', deps, re.MULTILINE)

  # (DON'T) remove the lastchange hook.
  # deps = re.sub(r"\{[^}]+LASTCHANGE.blink[^}]+\},\s*", '', deps, re.MULTILINE)

  # Assume that if DEPS is still python-parsable we succeeded.
  assert ast.parse(deps), 'DEPS smoke test (AST parsing) failed'
  return deps

if __name__ == '__main__':
  if len(sys.argv) > 1:
    print >>sys.stderr, 'Updating DEPS from file: ', sys.argv[1]
    with open(sys.argv[1]) as f:
     input_deps = f.read()
  else:
    print >>sys.stderr, 'Reading DEPS from stdin'
    input_deps = sys.stdin.read()

  output_deps = CleanupDeps(input_deps)

  if len(sys.argv) > 1:
    with open(sys.argv[1], 'w') as f:
      f.write(output_deps)
  else:
    print output_deps
