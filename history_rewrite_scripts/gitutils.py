# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""
A collection of classes and function to read and write git objects.
"""

import hashlib
import os
import subprocess
import zlib


class _AbstractGitObjDB(object):
  """Base class for GitReadonlyObjDB and GitLooseObjDB."""
  def ReadObj(self, sha1):
    raise NotImplementedError()

  def WriteObj(self, objtype, payload):
    raise NotImplementedError()

  def ReadCommit(self, sha1):
    objtype, payload = self.ReadObj(sha1)
    assert objtype == 'commit', '%s is not a commit (%s)' % (sha1, objtype)
    return Commit(payload)

  def ReadTree(self, sha1):
    objtype, payload = self.ReadObj(sha1)
    assert objtype == 'tree', '%s is not a tree (%s)' % (sha1, objtype)
    return ParseTree(payload)

  def ReadBlob(self, sha1):
    objtype, payload = self.ReadObj(sha1)
    assert objtype == 'blob', '%s is not a blob (%s)' % (sha1, objtype)
    return payload

  def WriteCommit(self, payload):
    return self.WriteObj('commit', payload)

  def WriteTree(self, entries):
    payload = ''
    for entry in sorted(entries, key=_GitTreeEntryGetSortKey):
      payload += entry[0] + ' ' + entry[1] + '\x00' + entry[2].decode('hex')
    return self.WriteObj('tree', payload)

  def WriteBlob(self, data):
    return self.WriteObj('blob', data)

  def CopyBlobIntoFile(self, sha1, file_path):
    WriteFileAtomic(file_path, self.ReadBlob(sha1))

  def Close(self):
    pass


class GitReadonlyObjDB(_AbstractGitObjDB):
  """Reads arbitrary objects (packed or loose) from a repo using the git binary.

  Pro: can read from both pack files and loose objects.
  Cons: does not support writing; it is slow (pipes everything trough git).
  """
  def __init__(self, git_dir=None):
    self._proc = subprocess.Popen(['git', 'cat-file', '--batch'],
                                  stdout=subprocess.PIPE,
                                  stdin=subprocess.PIPE,
                                  cwd=git_dir)

  def ReadObj(self, sha1):
    assert len(sha1) == 40
    self._proc.stdin.write(sha1 + '\n')
    line = self._proc.stdout.readline().strip('\r\n')
    parts = line.split()
    if len(parts) != 3:
      print 'PAAAAAAA', parts
      import sys
      sys.exit(1)
    ret_sha1, objtype, size = line.split()
    assert sha1 == ret_sha1
    payload = self._proc.stdout.read(int(size))
    assert VerifyObject(objtype, payload, sha1)
    assert self._proc.stdout.read(1) == '\n'
    return objtype, payload

  def WriteObj(self, objtype, payload):
    raise NotImplementedError('Write not supported in GitReadonlyObjDB')

  def Close(self):
    try:
      self._proc.terminate()
    except:
      pass



class GitLooseObjDB(_AbstractGitObjDB):
  """Reads/Writes loose git objects.

  Pros: can both read and write objects; it's blazing fast.
  Con: it can ready only loose objects (no objects from packs).
  """
  def __init__(self, objdir=None):
    self._objdir = objdir

  def ReadObj(self, sha1):
    assert len(sha1) == 40
    objpath = os.path.join(self._objdir, sha1[0:2], sha1[2:])
    with open(objpath, 'rb') as fin:
      data = zlib.decompress(fin.read())
    headlen = data.index('\x00')
    objtype, objlen = data[:headlen].split()
    objlen = int(objlen)
    payload = data[headlen + 1:]
    assert len(data) == (objlen + headlen + 1)
    return objtype, payload

  def WriteObj(self, objtype, payload):
    data = ('%s %d\x00' % (objtype, len(payload))) + payload
    hasher = hashlib.sha1()
    hasher.update(data)
    sha1 = hasher.hexdigest()
    basedir = os.path.join(self._objdir, sha1[0:2])
    objpath = os.path.join(basedir, sha1[2:])
    if not os.path.exists(objpath):
      Makedirs(basedir)
      WriteFileAtomic(objpath, zlib.compress(data, 1))
    return sha1


class Commit(object):
  """Semi-structured representation of a commit object."""
  def __init__(self, payload):
    headers, self.message = payload.split('\n\n', 1)
    self.headers = {}
    self.merged_parent = None
    for header, value in (h.split(' ', 1) for h in headers.split('\n')):
      assert header not in self.headers, 'Duplicate ' + header
      self.headers[header] = value
    assert 'tree' in self.headers
    assert 'author' in self.headers
    assert 'committer' in self.headers

  @property
  def parent(self):
    """Returns the SHA1 of the parent commit or None."""
    return self.headers.get('parent')

  @parent.setter
  def parent(self, value):
    self.headers['parent'] = value

  @property
  def tree(self):
    """Returns the SHA1 of the tree."""
    return self.headers.get('tree')

  @tree.setter
  def tree(self, value):
    self.headers['tree'] = value

  @property
  def author(self):
    """Returns author header."""
    return self.headers.get('author')

  @author.setter
  def author(self, value):
    self.headers['author'] = value

  @property
  def committer(self):
    """Returns the committer header."""
    return self.headers.get('committer')

  @committer.setter
  def committer(self, value):
    self.headers['committer'] = value

  @property
  def payload(self):
    """Returns the raw object payload."""
    payload = 'tree ' + self.headers['tree']
    if self.parent:
      payload += '\nparent ' + self.headers['parent']
    if self.merged_parent:
      payload += '\nparent ' + self.merged_parent
    payload += '\nauthor ' + self.headers['author']
    payload += '\ncommitter ' + self.headers['committer']
    payload += '\n\n'
    payload += self.message
    return payload


def Makedirs(path):
  """like os.makedirs, ignore errors if already exists."""
  try:
    os.makedirs(path)
  except OSError:
    pass


def WriteFileAtomic(file_path, data):
  """Writes a file atomically (write to .tmp and rename)."""
  tmp_path = '%s-%s.tmp' % (file_path, os.getpid())
  with open(tmp_path, 'wb') as tmp_file:
    tmp_file.write(data)
  os.rename(tmp_path, file_path)


def TreeLookup(entries, entry_name):
  """Returns the sha1 for the given blob/subtree name if any, or None."""
  sha1s = [e[2] for e in entries if e[1] == entry_name]
  return sha1s[0] if sha1s else None


def ReplaceInTree(entries, entry_name, replacement_sha1):
  """Replaces the blob/subtree named |entry_name| with the given sha1"""
  new_entries = []
  did_replace = False
  for entry in entries:
    if entry[1] == entry_name:
      new_entries.append((entry[0], entry[1], replacement_sha1))
      did_replace = True
    else:
      new_entries.append(entry)
  assert did_replace, 'Could not find %s in tree' % entry_name
  return new_entries


def VerifyObject(objtype, payload, expected_sha1):
  """Verifies the consistency of the given git object."""
  assert len(expected_sha1) == 40
  data = ('%s %d\x00' % (objtype, len(payload))) + payload
  hasher = hashlib.sha1()
  hasher.update(data)
  return hasher.hexdigest() == expected_sha1


def ParseTree(payload):
  """Returns a sorted list of tupled (mode, fname, sha1)"""
  cursor = 0
  entries = []
  while cursor < len(payload):
    cs1 = payload.find(' ', cursor)
    cs2 = payload.find('\0', cursor)
    mode = payload[cursor:cs1]
    fname = payload[(cs1 + 1):cs2]
    sha1 = payload[(cs2 + 1):(cs2 + 21)].encode('hex')
    assert len(sha1) == 40
    cursor = cs2 + 21
    entries.append((mode, fname, sha1))
  return entries


def _GitTreeEntryGetSortKey(entry):
  """Sorts entries in a git tree."""
  if entry[0][-5:-3] == '40':  # mode starts with 04 -> entry is a subtree.
    return entry[1] + '/'  # Git tree sorting is awkward. See goo.gl/Xfh0BX.
  else:
    return entry[1]
