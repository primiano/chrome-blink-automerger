#!/usr/bin/env python
# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import optparse
import os
import re
import subprocess
import sys
import time
import traceback

import gitutils
import blink_rewriter


CHROMIUM_REPO_URL = 'https://chromium.googlesource.com/chromium/src.git'

class _DIRS:
  NEWOBJS = None   # Where the new git objects (trees, blobs) will be put.
  CHROMIUM = None

class _GITDB:
  ORIG = None  # An instance of GitReadonlyObjDB
  NEW = None  # An instance of GitLooseObjDB


def main():
  parser = optparse.OptionParser()
  parser.add_option('--no-clobber', '-n', action='store_true', help='Keep the '
      ' original trees and the translation cache from the previous run (only '
      ' to speed up testing)')
  parser.add_option('--rev-list', '-r', default='refs/heads/master')
  parser.add_option('--keep-blob-cache', '-k', action='store_true')
  options, _ = parser.parse_args()

  base_dir = os.path.abspath(os.getcwd())
  _DIRS.CHROMIUM = os.path.join(base_dir, 'chromium.git')
  _DIRS.NEWOBJS = os.path.join(base_dir, 'new_objects')
  _DIRS.MERGEREPO = os.path.join(base_dir, 'blink-formatted.git')


  print '--------------------------------------------------------'
  print '             Blink mass clang-formatter'
  print '--------------------------------------------------------'

  git_version = subprocess.check_output(['git', '--version']).strip()
  print 'Git version:           ', git_version
  print ''

  if not options.no_clobber:
    _Rmtree(_DIRS.CHROMIUM)
  if not os.path.exists(_DIRS.CHROMIUM):
    cmd = ['git', 'clone', '--mirror', CHROMIUM_REPO_URL, _DIRS.CHROMIUM]
    print 'Cloning chromium: ', ' '.join(cmd)
    subprocess.check_call(cmd)

  if not options.no_clobber:
    _Rmtree(_DIRS.NEWOBJS)
  blobs_cache_path = os.path.join(_DIRS.NEWOBJS, 'blobs.cache')
  if not options.keep_blob_cache and os.path.exists(blobs_cache_path):
    os.unlink(blobs_cache_path)

  if not os.path.exists(_DIRS.NEWOBJS):
    os.makedirs(_DIRS.NEWOBJS)
  if os.path.exists(_DIRS.MERGEREPO):
    _Rmtree(_DIRS.MERGEREPO)

  _GITDB.ORIG = gitutils.GitReadonlyObjDB(_DIRS.CHROMIUM)
  _GITDB.NEW = gitutils.GitLooseObjDB(_DIRS.NEWOBJS)

  print 'Initializing the formatted repo'
  subprocess.check_call(['git', 'clone', '--bare', '--shared', _DIRS.CHROMIUM,
                        _DIRS.MERGEREPO])
  alt_obj_path = os.path.join(_DIRS.MERGEREPO, 'objects', 'info', 'alternates')
  with open(alt_obj_path,'a') as alt_fd:
    alt_fd.write('\n%s' % os.path.join(_DIRS.MERGEREPO, 'objects'))
    alt_fd.write('\n%s' % _DIRS.NEWOBJS)

  if options.no_clobber:
    blink_rewriter.LoadTreeCacheForTests(os.path.join(_DIRS.NEWOBJS, 'cache'))

  merge_heads = []  # ('chromium ref', 'blink ref', 'merge sha1 in chromium')
  blink_rewritten_sha1 = blink_rewriter.RewriteBlinkHistory(
        options.rev_list, _DIRS.CHROMIUM, _DIRS.NEWOBJS)

  if options.no_clobber:
    blink_rewriter.StoreTreeCacheForTests(os.path.join(_DIRS.NEWOBJS, 'cache'))

  print '\n\n'
  print blink_rewritten_sha1


def _Rmtree(dirpath):
  if os.path.exists(dirpath):
    subprocess.check_call(['rm', '-rf', dirpath])
    assert not os.path.exists(dirpath)

if __name__ == '__main__':
  main()
