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

import config
import deps_cleanup
import gitutils
import blink_rewriter


class _DIRS:
  NEWOBJS = None   # Where the new git objects (trees, blobs) will be put.
  CHROMIUM = None
  BLINK = None
  BLINKOBJS = None
  MERGEREPO = None

class _GITDB:
  ORIG = None  # An instance of GitReadonlyObjDB
  NEW = None  # An instance of GitLooseObjDB


def main():
  parser = optparse.OptionParser()
  parser.add_option('--no-clobber', '-n', action='store_true', help='Keep the '
      ' original trees and the translation cache from the previous run (only '
      ' to speed up testing)')
  options, _ = parser.parse_args()

  base_dir = os.path.abspath(os.getcwd())
  _DIRS.BLINK = os.path.join(base_dir, 'blink.git')
  _DIRS.BLINKOBJS = os.path.join(_DIRS.BLINK, 'objects')
  _DIRS.CHROMIUM = os.path.join(base_dir, 'chromium.git')
  _DIRS.MERGEREPO = os.path.join(base_dir, 'chrome-blink-merge.git')
  _DIRS.NEWOBJS = os.path.join(base_dir, 'new_objects')

  print '--------------------------------------------------------'
  print '             Chromium + Blink automerger'
  print '--------------------------------------------------------'

  git_version = subprocess.check_output(['git', '--version']).strip()
  print 'Git version:           ', git_version
  print 'Original chromium dir: ', _DIRS.CHROMIUM
  print 'Original blink dir:    ', _DIRS.BLINK
  print 'Merged repo dir:       ', _DIRS.MERGEREPO
  print ''

  if not options.no_clobber:
    _Rmtree(_DIRS.BLINK)
  if not os.path.exists(_DIRS.BLINK):
    cmd = ['git', 'clone', '--mirror', config.BLINK_REPO_URL, _DIRS.BLINK]
    print 'Cloning blink: ', ' '.join(cmd)
    subprocess.check_call(cmd)

  if not options.no_clobber:
    _Rmtree(_DIRS.CHROMIUM)
  if not os.path.exists(_DIRS.CHROMIUM):
    cmd = ['git', 'clone', '--mirror', config.CHROMIUM_REPO_URL, _DIRS.CHROMIUM]
    print 'Cloning chromium: ', ' '.join(cmd)
    subprocess.check_call(cmd)

  _Rmtree(_DIRS.MERGEREPO)

  if not options.no_clobber:
    _Rmtree(_DIRS.NEWOBJS)
  if not os.path.exists(_DIRS.NEWOBJS):
    os.makedirs(_DIRS.NEWOBJS)

  _GITDB.ORIG = gitutils.GitReadonlyObjDB(_DIRS.CHROMIUM)
  _GITDB.NEW = gitutils.GitLooseObjDB(_DIRS.NEWOBJS)

  print 'Initializing the merge repo'
  subprocess.check_call(['git', 'clone', '--bare', '--shared', _DIRS.CHROMIUM,
                        _DIRS.MERGEREPO])
  alt_obj_path = os.path.join(_DIRS.MERGEREPO, 'objects', 'info', 'alternates')
  with open(alt_obj_path,'a') as alt_fd:
    alt_fd.write('\n%s' % os.path.join(_DIRS.BLINK, 'objects'))
    alt_fd.write('\n%s' % _DIRS.NEWOBJS)

  if options.no_clobber:
    blink_rewriter.LoadTreeCacheForTests(os.path.join(_DIRS.NEWOBJS, 'cache'))

  merge_heads = []  # ('chromium ref', 'blink ref', 'merge sha1 in chromium')
  for chromium_ref, blink_ref in config.BRANCHES_TO_MERGE:
    chromium_sha1 = subprocess.check_output(['git', 'rev-parse', chromium_ref],
                                            cwd=_DIRS.CHROMIUM).strip()
    blink_rewritten_sha1 = blink_rewriter.RewriteBlinkHistory(
        blink_ref, _DIRS.BLINK, _DIRS.NEWOBJS)
    merge_sha1 = _MergeBlinkIntoChrome(chromium_sha1, blink_rewritten_sha1)
    merge_heads.append((chromium_ref, blink_ref, merge_sha1))
    print 'Merged @ %s in %s' % (merge_sha1[0:12], _DIRS.MERGEREPO)
    cmd = ['git', 'update-ref', chromium_ref, merge_sha1]
    subprocess.check_call(cmd, cwd=_DIRS.MERGEREPO)

  if options.no_clobber:
    blink_rewriter.StoreTreeCacheForTests(os.path.join(_DIRS.NEWOBJS, 'cache'))

  print '\n\n'
  print '----------------------------------------------'
  print '             RESULT OF THE MERGE'
  print '----------------------------------------------'
  for chromium_ref, blink_ref, merge_sha1 in merge_heads:
    print '%-26s + %-32s -> %s' % (chromium_ref, blink_ref, merge_sha1)
  print ' '
  print 'You should now:'
  print '  cd %s' %  _DIRS.MERGEREPO
  print '  git fsck'
  print '  git push %s %s' % (config.CHROMIUM_REPO_URL,
                              ' '.join(b[0] for b in config.BRANCHES_TO_MERGE))
  print ''
  print 'Note: the repo has "alternates" references to the original blink and'
  print 'chromium repos. If you need a standalone pack run:'
  print '  git repack -a -d --window=50 --depth=100'


def _MergeBlinkIntoChrome(chromium_sha1, blink_sha1):
  # blink_sha1 points to a rewritten revision where Blink has been pushed into
  # third_party/WebKit/ already.
  # We want to merge the subtree in BLINK_REWRITTEN/third_party/WebKit into
  # CHROMIUM/third_party/.

  # Retrieve third_party_tree, which is the tree inside the Chromium containing the
  cr_commit = _GITDB.ORIG.ReadCommit(chromium_sha1)
  cr_last_commit_time = int(cr_commit.headers['committer'].rsplit(' ',2)[-2])
  cr_root_tree = _GITDB.ORIG.ReadTree(cr_commit.tree)
  cr_3party_tree_sha1 = gitutils.TreeLookup(cr_root_tree, 'third_party')
  assert cr_3party_tree_sha1, 'No /third_party in %s' % chromium_sha1
  cr_3party_tree = _GITDB.ORIG.ReadTree(cr_3party_tree_sha1)
  assert gitutils.TreeLookup(cr_3party_tree, 'WebKit') is None, (
      'WebKit seems already merged in %s' % chromium_sha1)

  # remove WebKit references from .gitignore
  cr_gitignore_sha1 = gitutils.TreeLookup(cr_root_tree, '.gitignore')
  assert cr_gitignore_sha1, 'No .gitignore in %s' % chromium_sha1
  cr_gitignore_lines = _GITDB.ORIG.ReadBlob(cr_gitignore_sha1).splitlines()
  GITIGNORE_LINE = '/third_party/WebKit'
  assert GITIGNORE_LINE in cr_gitignore_lines, (
      'No %s in .gitignore in %s' % (GITIGNORE_LINE, chromium_sha1))
  cr_gitignore_lines = [l for l in cr_gitignore_lines if l != GITIGNORE_LINE]
  cr_gitignore = '\n'.join(cr_gitignore_lines)
  cr_gitignore_sha1 = _GITDB.NEW.WriteBlob(cr_gitignore)

  # remove WebKit references from DEPS
  deps_sha1 = gitutils.TreeLookup(cr_root_tree, 'DEPS')
  assert deps_sha1, 'No DEPS in %s' % chromium_sha1
  deps = _GITDB.ORIG.ReadBlob(deps_sha1)
  deps = deps_cleanup.CleanupDeps(deps)
  deps_sha1 = _GITDB.NEW.WriteBlob(deps)

  # cr_3party_tree at this point contains stuff like cld, libjpeg,
  # but NOT WebKit (yet).

  # Now retrieve the WebKit tree inside third_party from the rewritten blink
  # history.
  bl_commit = _GITDB.NEW.ReadCommit(blink_sha1)
  bl_root_tree = _GITDB.NEW.ReadTree(bl_commit.tree)
  assert len(bl_root_tree) == 1 and bl_root_tree[0][1] == 'third_party'
  bl_3party_tree_sha1 = bl_root_tree[0][2]
  bl_3party_tree = _GITDB.NEW.ReadTree(bl_3party_tree_sha1)
  assert len(bl_3party_tree) == 1 and bl_3party_tree[0][1] == 'WebKit'
  bl_webkit_tree_sha1 = bl_3party_tree[0][2]

  cr_merge_3party_tree = (cr_3party_tree +
                          [('40000', 'WebKit', bl_webkit_tree_sha1)])
  cr_merge_3party_tree_sha1 = _GITDB.NEW.WriteTree(cr_merge_3party_tree)
  cr_merge_root_tree = gitutils.ReplaceInTree(
      cr_root_tree, 'third_party', cr_merge_3party_tree_sha1)
  cr_merge_root_tree = gitutils.ReplaceInTree(
      cr_merge_root_tree, '.gitignore', cr_gitignore_sha1)
  cr_merge_root_tree = gitutils.ReplaceInTree(
      cr_merge_root_tree, 'DEPS', deps_sha1)
  cr_merge_root_tree_sha1 = _GITDB.NEW.WriteTree(cr_merge_root_tree)

  # Work out the Cr-Commit-Position of the latest chromium commit.
  cr_ref = re.findall(r'^Cr-Commit-Position: (.+)@\{#(\d+)\}$',
                      cr_commit.message, re.MULTILINE)
  assert cr_ref, 'Cannot find Cr-Commit-Position in %s' % chromium_sha1
  cr_ref = cr_ref[0]

  bl_ref = re.findall(r'^git-svn-id: svn://svn.chromium.org(.+)@(\d+) ',
                      bl_commit.message, re.MULTILINE)
  assert bl_ref, 'Cannot find git-svn-id in %s' % blink_sha1
  bl_ref = bl_ref[0]

  # Pretend that the commit happened 5 minutes after the last commit on the
  # branch. This is to make it so that the merge operation is idempotent and
  # repeatable.
  cr_merge_commit_time = cr_last_commit_time + 300
  cr_merge_msg = config.MERGE_MSG % { 'chromium_sha': chromium_sha1,
                                      'chromium_branch': cr_ref[0],
                                      'chromium_pos':  cr_ref[1],
                                      'chromium_next_pos': int(cr_ref[1]) + 1,
                                      'blink_sha': blink_sha1,
                                      'blink_branch': bl_ref[0],
                                      'blink_rev': bl_ref[1],
                                    }

  cr_merge_commit = cr_commit
  cr_merge_commit.headers['author'] = '%s <%s> %d +0000' % (
      config.AUTOMERGER_NAME, config.AUTOMERGER_EMAIL, cr_merge_commit_time)
  cr_merge_commit.headers['committer'] = cr_merge_commit.headers['author']
  cr_merge_commit.tree = cr_merge_root_tree_sha1
  cr_merge_commit.parent = chromium_sha1
  cr_merge_commit.merged_parent = blink_sha1
  cr_merge_commit.message = cr_merge_msg
  cr_merge_commit_sha1 = _GITDB.NEW.WriteCommit(cr_merge_commit.payload)
  return cr_merge_commit_sha1


def _Rmtree(dirpath):
  if os.path.exists(dirpath):
    subprocess.check_call(['rm', '-rf', dirpath])
    assert not os.path.exists(dirpath)

if __name__ == '__main__':
  main()