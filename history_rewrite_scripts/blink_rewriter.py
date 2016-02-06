# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import multiprocessing
import os
import subprocess
import sys
import traceback

import eta_estimator
import gitutils


# Set of extensions to clang-format
_SRC_EXTS = ({'.cpp', '.cc', '.h'})
_CLANG_FORMAT_PATH = './clang-format'
_CLANG_FORMAT_CWD = '/mnt'

# Global dir constants (set by RewriteBlinkHistory and read by subprocesses).
class _DIRS:
  ROOT_DIR = None  # Blink git dir (the one containing objects/ refs/ etc.)
  NEWOBJS = None   # Where the new git objects (trees, blobs) will be stored.

# Per-process (i.e. initialized after spawn) instances of gitutils classes.
class _GITDB:
  ORIG = None  # An instance of GitReadonlyObjDB
  NEW = None  # An instance of GitLooseObjDB

# Cross-process shared cache of rewritten trees.
_tree_cache = multiprocessing.Manager().dict()

# Cross-process shared cache of rewritten blobs.
_blob_cache = multiprocessing.Manager().dict()


def RewriteBlinkHistory(branch, blink_git_dir, new_obj_dir):
  """Rewrites the history of the given blink branch

  The rewrite consists of the following:
    For each commit reachable by |branch|:
      - Remove all .png files (see _BIN_EXTS) from the /LayoutTests directory.
      - Make the root tree a subtree of /third_party/WebKit/ (i.e. pretend that
        all commits always happened in third_party/WebKit).

  Args:
    branch: full ref to the branch to rewrite (e.g. refs/heads/master).
    blink_git_dir: path to the source Blink git dir (will not be modified).
    new_obj_dir: where the newly created git objects will be stored.

  Returns:
    The SHA1 (40 chars hex string) of the rewritten head.
  """
  _DIRS.ROOT_DIR = blink_git_dir
  _DIRS.NEWOBJS = new_obj_dir
  blobs_cache_path = os.path.join(new_obj_dir, 'blobs.cache')

  _InitGitDBForCurrentProcess()  # Init db for the main process.

  print '\nRewriting blink history for %s' % branch
  print '--------------------------------------------------------'
  assert os.path.isdir(_DIRS.NEWOBJS)

  commits, trees = _LoadRevlist(branch)
  print 'First commit to rewrite: ', subprocess.check_output(
      ['git', 'log', '-1', r'--format=%h %cd %s', commits[0]],
      cwd=_DIRS.ROOT_DIR).strip()
  print 'Last commit to rewrite:  ', subprocess.check_output(
      ['git', 'log', '-1', r'--format=%h %cd %s', commits[-1]],
      cwd=_DIRS.ROOT_DIR).strip()
  print 'Num commits to rewrite:  ', len(commits)

  print '\nPhase 1/4: extracting set of files to clang-format'
  if os.path.exists(blobs_cache_path):
    blobs = LoadBlobCacheForTests(blobs_cache_path)
  else:
    blobs = set()
    eta = eta_estimator.ETA(len(trees), unit='trees')
    blobs_tree_cache = set()
    for tree in trees:
      _BuildBlobsSet(tree, blobs, blobs_tree_cache)
      eta.job_completed()
    print '  Will clang-format %d distinct files' % len(blobs)
    StoreBlobCacheForTests(blobs, blobs_cache_path)

  print '\nPhase 2/4: rewriting blobs in parallel'
  _RewriteBlobs(blobs)

  print '\nPhase 3/4: rewriting trees in parallel'
  _RewriteTrees(trees)

  print '\nPhase 4/4: rewriting commits serially'
  rewriten_head_sha1 = _RewriteCommits(commits)
  print '--------------------------------------------------------'

  return rewriten_head_sha1


def _InitGitDBForCurrentProcess():
  """Called by both the main and the pool's subprocesses to get a unique
  instance per process."""
  if _GITDB.ORIG:
    _GITDB.ORIG.Close()
  _GITDB.ORIG = gitutils.GitReadonlyObjDB(_DIRS.ROOT_DIR)
  _GITDB.NEW = gitutils.GitLooseObjDB(_DIRS.NEWOBJS)


def _BuildBlobsSet(tree_sha1, whitelist, tree_cache, depth=0):
  assert len(tree_sha1) == 40
  if tree_sha1 in tree_cache:
    return
  tree_cache.add(tree_sha1)
  tree_entries = _GITDB.ORIG.ReadTree(tree_sha1)
  for mode, fname, sha1 in tree_entries:
    if mode[0] == '1':  # It's a file
      if depth < 2:
        continue
      _, ext = os.path.splitext(fname)
      if ext.lower() in _SRC_EXTS:
        whitelist.add(sha1)
        continue
    else:
      assert mode == '40000'
      if ((depth == 0 and fname == 'third_party') or
          (depth == 1 and fname == 'WebKit') or
           depth >= 2):
        _BuildBlobsSet(sha1, whitelist, tree_cache, depth + 1)


def _RewriteBlobs(blobs):
  pool = multiprocessing.Pool(initializer=_InitGitDBForCurrentProcess,
                              processes=multiprocessing.cpu_count() * 3)
  eta = eta_estimator.ETA(len(blobs), unit='blobs')
  for _ in pool.imap_unordered(_RewriteOneBlobWrapper, blobs):
    eta.job_completed()
  pool.close()
  pool.join()


def _RewriteOneBlobWrapper(blobish):
  """Entry point of each subprocess job."""
  # Need this try block to deal properly with exceptions in multiprocessing.
  try:
    _RewriteOneBlob(blobish)
  except Exception as e:
    sys.stderr.write('\n' + traceback.format_exc())
    raise


def _RewriteOneBlob(sha1):
  proc = subprocess.Popen([_CLANG_FORMAT_PATH], cwd=_CLANG_FORMAT_CWD,
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE)
  orig_content = _GITDB.ORIG.ReadBlob(sha1)
  (stdout, stderr) = proc.communicate(orig_content)
  assert not stderr
  new_sha1 = _GITDB.NEW.WriteBlob(stdout)
  _blob_cache[sha1] = new_sha1


def _RewriteTrees(trees):
  pool = multiprocessing.Pool(initializer=_InitGitDBForCurrentProcess)
  eta = eta_estimator.ETA(len(trees), unit='trees')
  for _ in pool.imap_unordered(_RewriteOneTreeWrapper, trees):
    eta.job_completed()
  pool.close()
  pool.join()


def _RewriteOneTreeWrapper(treeish):
  """Entry point of each subprocess job."""
  # Need this try block to deal properly with exceptions in multiprocessing.
  try:
    # Do not bother checking if we already translated the tree. It is extremely
    # unlikely (i.e. empty commits) and is not worth the overhead of doing that.
    _RewriteOneTree(treeish)
  except Exception as e:
    sys.stderr.write('\n' + traceback.format_exc())
    raise


def _RewriteOneTree(tree_sha1, depth=0, in_webkit_dir=False):
  assert len(tree_sha1) == 40
  cached_translation = _tree_cache.get(tree_sha1)
  if cached_translation:
    return cached_translation

  changed = False
  entries = []
  tree_entries = _GITDB.ORIG.ReadTree(tree_sha1)
  for mode, fname, sha1 in tree_entries:
    if mode[0] == '1':  # It's a file
      _, ext = os.path.splitext(fname)
      if (in_webkit_dir and ext.lower() in _SRC_EXTS):
        old_sha1 = sha1
        sha1 = _blob_cache.get(sha1)
        assert(sha1, 'Cache miss (blob %s) from phase 2' % sha1)
        changed = old_sha1 != sha1
    else:
      assert mode == '40000'
      if ((depth == 0 and fname == 'third_party') or
          (depth == 1 and fname == 'WebKit') or
          in_webkit_dir):
        old_sha1 = sha1
        in_wk = in_webkit_dir or (depth == 1 and fname == 'WebKit')
        sha1 = _RewriteOneTree(sha1, depth + 1, in_wk)
        changed = True if old_sha1 != sha1 else changed
    entries.append((mode, fname, sha1))

  if changed:
    res = _GITDB.NEW.WriteTree(entries)
  else:
    res =  tree_sha1

  # If there is a collision (another process translated the same tree) check
  # pedantically that the translated tree has the same SHA1.
  collision = _tree_cache.setdefault(tree_sha1, res)
  assert collision == res
  return res


def _LoadRevlist(branch='master'):
  """Returns a tuple of two lists: commitish(es), treeish(es)."""
  commits = []
  trees = []
  cmd = ['git', 'rev-list', '--format=%T', '--reverse', branch]
  print 'Running [%s], might take some minutes' % ' '.join(cmd),
  sys.stdout.flush()
  proc = subprocess.Popen(
      cmd, stdout=subprocess.PIPE, cwd=_DIRS.ROOT_DIR, bufsize=1048576)
  commit_sha = None
  tree_sha = None
  while True:
    line = proc.stdout.readline()
    if not line:
      break
    line = line.rstrip('\r\n')
    if line.startswith('commit'):
      commit_sha = line[7:]
    else:
      tree_sha = line
      assert len(commit_sha) == 40
      assert len(tree_sha) == 40
      commits.append(commit_sha)
      trees.append(tree_sha)
      commit_sha = tree_sha = None
  print '\r%120s\r' % '',
  return commits, trees


def _RewriteCommits(revs):
  translated_trees = _tree_cache.copy()  # Un-proxied local copy for faster lookups.
  translated_commits = {}  # orig commitish -> rewritten commitish
  eta = eta_estimator.ETA(len(revs), unit='commits')
  _InitGitDBForCurrentProcess()
  for rev in revs:
    commit = _GITDB.ORIG.ReadCommit(rev)
    new_tree = translated_trees[commit.tree]
    assert len(new_tree) == 40
    commit.tree = new_tree
    if commit.parent:
      if commit.parent not in translated_commits:
        print >>sys.stderr, ('%s depends on %s, which has not been rewritten. Reusing original commit' % (
            rev[0:12],commit.parent[0:12]))
        # assert False
        #commit.parent = None
      else:
        commit.parent = translated_commits[commit.parent]
    try:
      translated_commit = _GITDB.NEW.WriteCommit(commit.payload)
    except:
      print 'FAILED on ', rev
      print 'Payload: ', commit.payload
      raise
    translated_commits[rev] = translated_commit
    eta.job_completed()
  old_head = revs[-1]
  new_head = translated_commits[old_head]
  print 'New blink head is %s (which corresponds to %s)' % (
      new_head[0:12], old_head[0:12])
  return new_head

################################################################################
# Testing stuff
################################################################################

def LoadTreeCacheForTests(cache_db_path):
  import json
  if os.path.exists(cache_db_path) and os.path.getsize(cache_db_path):
    print 'Loading translations from %s' % cache_db_path
    with open(cache_db_path, 'r') as f:
      for k,v in json.load(f).iteritems():
        _tree_cache[str(k)] = str(v)
      print 'Loaded %d translations from cache' % len(_tree_cache)

def StoreTreeCacheForTests(cache_db_path):
  import json
  with open(cache_db_path, 'w') as f:
    json.dump(_tree_cache.copy(), f)

def LoadBlobCacheForTests(cache_db_path):
  import json
  if os.path.exists(cache_db_path) and os.path.getsize(cache_db_path):
    print 'Loading blobs cache from %s' % cache_db_path
    with open(cache_db_path, 'r') as f:
      return set(json.load(f))

def StoreBlobCacheForTests(blobs, cache_db_path):
  import json
  with open(cache_db_path, 'w') as f:
    json.dump(list(blobs), f)
