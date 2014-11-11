#!/bin/bash
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# The following branches are involved in the dance:
# chromium/master       : upstream Chromium ToT (linear)
# blink/master          : upstream Blink ToT (linear)
# origin/blink-rewrite  : rewrite of blink/master (linear). Commits are rebased
#                         into a subtree, from * -> third_party/WebKit/*
# origin/master_tot     : continuous merge of Chromium + Blink ToT (rewritten),
#                         stripping also WebKit from .gitignore and DEPS.
# origin/master_pinned  : this is always a single merge commit of Chromium ToT +
#                         the corresponding rewritten Blink (@DEPS) and is force
#                         pushed every time (to deal with reverts of rolls).

# Layout of origin/master_tot:
# blink/master           Ba <- Bb <- Bc <- Bd <- Be <- Bf (ToT)
# origin/blink-rewrite   Ra <- Rb <- Rc <- Rd <- Re <- Rf (ToT)
#                          \    \           \           \
# origin/master_tot         T1 < T2    <-   T3    <-    T4
#                          /___ /      _____/     _____/
# chromium/master        C1       <- C2       <- C3 (ToT)

# Layout of origin/master_pinned (imagining C3:DEPS pins Blink @ revision 'Be'):
# origin/blink-rewrite   Ra <- Rb <- Rc <- Rd <- Re <- Rf (ToT)
#                                                 \
# origin/master_pinned                             HEAD
#                                                 /
# chromium/master        C1       <- C2       <- C3 (ToT)

source "$(dirname $0)/vars.sh"

WORKDIR="${HOME}/workdir.git"

export GIT_AUTHOR_NAME="${AUTOMERGER_GIT_NAME}"
export GIT_AUTHOR_EMAIL="${AUTOMERGER_GIT_EMAIL}"
export GIT_COMMITTER_NAME="${AUTOMERGER_GIT_NAME}"
export GIT_COMMITTER_EMAIL="${AUTOMERGER_GIT_EMAIL}"

set +e  # Bail out on any error.

print_step () {
  echo ''
  echo '***********************************************************************'
  echo "$*"
  echo '***********************************************************************'
}

with_backoff () {
  local attempts=5
  local timeout=30
  local exit_code=0

  while [ $attempts -gt 0 ]; do
    set +e
    "$@"
    exit_code=$?
    set -e

    [ $exit_code -eq 0 ] && break

    print_step "Command $@ failed, retrying in $timeout.."
    sleep $timeout
    attempts=$(( attempts - 1 ))
    timeout=$(( timeout * 2 ))
  done

  return $exit_code
}

# Looks up a corresponding commit ($1) in the given branch ($2) by looking at
# the git-svn-id (which is supposed to be unique). This is to find corresponding
# commits between blink/master and the origin/blink-rewrite.
lookup_by_svn_id() {
  local GIT_SVN_ID="$(git cat-file commit "$1" | grep '^git-svn-id')"
  local CORRESPONDING_SHA="$(git rev-list "$2" --grep "${GIT_SVN_ID}")"
  if [ "${CORRESPONDING_SHA}" = "" ]; then
    echo "Could not lookup $1 in $2 using ${GIT_SVN_ID}" >&2
    return 1
  fi
  echo "${CORRESPONDING_SHA}"
  return 0
}

# Generates a tree-ish which is the merge of a Chrome ($1) + a Blink ($2) trees.
# Furthermore it mangles DEPS and .gitignore to strip out third_party/WebKit.
merge_chromium_and_blink_trees() {
  rm -f index
  git read-tree --trivial "$1" "$2"
  MERGED_TREEISH="$(git write-tree)"

  # Remove DEPS and .gitignore from the tree (will mangle and readd them below).
  TMP_TREEDESC="$(mktemp)"
  git ls-tree "${MERGED_TREEISH}" | egrep -v "DEPS|\.gitignore" \
      > "${TMP_TREEDESC}"
  
  # Remove third_party/WebKit entries from DEPS and readd to the tree.
  TMP_DEPS="$(mktemp)"
  git show "${MERGED_TREEISH}:DEPS" | \
      egrep -v "chromium/blink.git|third_party/WebKit':" > "${TMP_DEPS}"
  DEPS_BLOB="$(git hash-object -w "${TMP_DEPS}")"
  rm -f "${TMP_DEPS}"
  /bin/echo -e "100644 blob ${DEPS_BLOB}\tDEPS" >> "${TMP_TREEDESC}"

  # Remove third_party/WebKit entries from .gitignore and readd to the tree.
  TMP_GITIGNORE="$(mktemp)"
  git show "${MERGED_TREEISH}:.gitignore" | \
      grep -v "/third_party/WebKit" > "${TMP_GITIGNORE}"
  GITIGNORE_BLOB="$(git hash-object -w "${TMP_GITIGNORE}")"
  rm -f "${TMP_GITIGNORE}"
  /bin/echo -e "100644 blob ${GITIGNORE_BLOB}\t.gitignore" >> "${TMP_TREEDESC}"
  
  # MERGE_TREEISH: chromium + blink-rewritten + mangled DEPS and .gitignore.
  MERGE_TREEISH="$(git mktree < "${TMP_TREEDESC}")"
  rm -f "${TMP_TREEDESC}"
  echo "${MERGE_TREEISH}"
  rm -f index
  return 0
}


##########
#  MAIN
##########

# If the push target is a local directory (i.e. the AM also act as a dumb HTTP
# server) prepare the directory.
if [ "${MERGED_REPO:0:1}" = "/" ]; then
  if [ ! -d "${MERGED_REPO}" ]; then
    mkdir -p "${MERGED_REPO}"
    (
      cd "${MERGED_REPO}"
      git init --bare
      git config pack.packSizeLimit 64m  # For dumb http protocol.
      mv hooks/post-update.sample hooks/post-update
    )
  fi
fi

if [ ! -d "${WORKDIR}" ]; then
  print_step "Setting up the git repo in ${WORKDIR}"
  mkdir -p "${WORKDIR}"
  cd "${WORKDIR}"
  git init --bare
  git remote add blink -t master "${BLINK_REPO}"
  git remote add chromium -t master "${CHROMIUM_REPO}"
  git remote add origin "${MERGED_REPO}"
fi

print_step "Syncing remotes"
cd "${WORKDIR}"
rm -f index  # Drop any stale index
rm -f pack/objects/pack/tmp_pack_*
with_backoff git remote update

print_step "Catching up and rewriting Blink history"
# Export these as they will be needed in the filter-branch subshells.
export LAST_REWRITTEN_SHA="$(git rev-parse origin/blink-rewrite)"

export LAST_BLINK_SHA_PROCESSED="$(lookup_by_svn_id "${LAST_REWRITTEN_SHA}" \
                                                    blink/master)"


echo "Last commit processed in blink/master: ${LAST_BLINK_SHA_PROCESSED}"
echo "Last commit rewritten in origin/blink-rewrite: ${LAST_REWRITTEN_SHA}"

# Do some math to doublecheck linearity of history.
N_COMMITS_UPSTREAM="$(git rev-list --count blink/master)"
N_COMMITS_REWRITTEN="$(git rev-list --count origin/blink-rewrite)"
N_COMMITS_TO_REWRITE="$(git rev-list --count \
                      ${LAST_BLINK_SHA_PROCESSED}..blink/master)"

echo "N_COMMITS_UPSTREAM   = ${N_COMMITS_UPSTREAM}"
echo "N_COMMITS_REWRITTEN  = ${N_COMMITS_REWRITTEN}"
echo "N_COMMITS_TO_REWRITE = ${N_COMMITS_TO_REWRITE}"
                      
if [ ${N_COMMITS_UPSTREAM} != \
     $((${N_COMMITS_REWRITTEN} + ${N_COMMITS_TO_REWRITE})) ]; then
  echo "Error: history not linear. "
  exit 1
fi

if [ ${N_COMMITS_TO_REWRITE} -gt 0 ]; then
  # Copy the upstream ToT ref into the "blink-rewrite" branch and switch to it. 
  git branch -q -f blink-rewrite blink/master
  git symbolic-ref HEAD refs/heads/blink-rewrite
  git branch blink-rewrite -q --set-upstream-to origin/blink-rewrite

  # This is a pretty hardcode piece of git black magic. The goal is rewriting
  # the history of Blink, in a way that make all the commits look like as if
  # they were created in $ROOT/third_party/WebKit instead of $ROOT/. Also, we
  # want (or, at least, I do) to do this without expensive operations which 
  # involve having a working copy and doing a lot of I/O.
  git filter-branch -f --commit-filter '
      TREE="$1"; shift; parent="$2"
      if [ "${parent}" = "${LAST_BLINK_SHA_PROCESSED}" ]; then
        parent="${LAST_REWRITTEN_SHA}"
      fi
      SUBTREE1="$(/bin/echo -e "040000 tree ${TREE}\tWebKit" | git mktree)"
      SUBTREE2="$(/bin/echo -e "040000 tree ${SUBTREE1}\tthird_party" | git mktree)"
      git commit-tree ${SUBTREE2} -p "${parent}"' -- \
      ${LAST_BLINK_SHA_PROCESSED}..blink-rewrite

  # At this point the "blink-rewrite" branch points to the head of the new chain
  # of commits rewritten.
  
  # Check that the number of total commits in the rewritten branch matches
  # the number of upstream commits.
  if [ $(git rev-list --count blink-rewrite) != ${N_COMMITS_UPSTREAM} ]; then
    echo "Linearity check post rewrite failed."
    exit 3
  fi

  # Paranoid check: the number of commits that we rewrote must match the number
  # of commits calculated before starting.
  if [ $(git rev-list --count ${LAST_REWRITTEN_SHA}..blink-rewrite) != \
      ${N_COMMITS_TO_REWRITE} ]; then
    echo "Linearity check of rewritten commits failed." 
    exit 4
  fi

  echo "Pushing the Blink history into origin/blink-rewrite"
  with_backoff git push origin "blink-rewrite:refs/heads/blink-rewrite"
else  # N_COMMITS_TO_REWRITE > 0
  echo "Nothing to be done"
fi

print_step "Merging Chromium ToT + Blink ToT"
N_COMMITS_TO_MERGE="$(git rev-list --count --no-merges \
                    chromium/master origin/blink-rewrite \
                    --not origin/master_tot)"

if [ ${N_COMMITS_TO_MERGE} -gt 0 ]; then
  git branch -q -f master_tot origin/master_tot
  git symbolic-ref HEAD refs/heads/master_tot
  
  MERGE_TREEISH="$(merge_chromium_and_blink_trees \
                 chromium/master origin/blink-rewrite)"
  
  # Create the merge commit.
  CHROME_SHA="$(git rev-parse chromium/master)"
  BLINK_REWRITTEN_SHA="$(git rev-parse origin/blink-rewrite)"
  PREV_MERGE_SHA="$(git rev-parse origin/master_tot)"
  BLINK_SHA="$(lookup_by_svn_id "${BLINK_REWRITTEN_SHA}" blink/master)"
  
  MERGE_COMMIT="$(git commit-tree "${MERGE_TREEISH}" \
      -p "${PREV_MERGE_SHA}" -p "${CHROME_SHA}" -p "${BLINK_REWRITTEN_SHA}" \
      -m "Merge ToT Chrome @ ${CHROME_SHA} + ToT Blink @ ${BLINK_SHA}")"
  
  echo "Pushing the merge commit ${MERGE_COMMIT} to origin/master_tot"
  git branch -q -f master_tot ${MERGE_COMMIT}
  with_backoff git push origin master_tot:refs/heads/master_tot
else  # N_COMMITS_TO_MERGE > 0
  echo "Nothing to be done"
fi

print_step "Merging Chromium ToT + Blink @ DEPS"
# Conversely to the previous case (ToT+ToT), the resulting history of this
# branch is not linear w.r.t. the merge commits generated by prior runs.
# This branch will end up always being one merge commit which has the chromium
# history on one side and the blink (rewritten) history on the other, but no
# parents with previous merge commits (which essentially get discarded at every
# new run). 
# Rationale: it is not feasiable to have a linear (merge) history in presence of
# blink rolls being reverted (i.e. is is not possible to merge an earlier point
# which has been already merged by a previous merge commit).
N_COMMITS_TO_MERGE="$(git rev-list --count --no-merges \
                    chromium/master --not origin/master_pinned)"

if [ ${N_COMMITS_TO_MERGE} -gt 0 ]; then
  git branch -q -f master_pinned origin/master_pinned
  git symbolic-ref HEAD refs/heads/master_pinned
  DEPS="$(git show chromium/master:DEPS)"
  PARSER_CODE="import sys; Var=lambda x:x; exec(sys.stdin.read()); \
               print vars['webkit_revision']"
  PINNED_BLINK_SHA="$(echo "${DEPS}" | python -c "${PARSER_CODE}")"
  echo "Pinned Blink commit (upstream):   ${PINNED_BLINK_SHA}"
  
  REWRITTEN_PINNED_SHA="$(lookup_by_svn_id "${PINNED_BLINK_SHA}" \
                                           "origin/blink-rewrite")"
  echo "Corresponding commit (rewritten): ${REWRITTEN_PINNED_SHA}"

  # Create the merge commit.
  MERGE_TREEISH="$(merge_chromium_and_blink_trees \
                 chromium/master "${REWRITTEN_PINNED_SHA}")"
  
  CHROME_SHA="$(git rev-parse chromium/master)"

  MERGE_COMMIT="$(git commit-tree "${MERGE_TREEISH}" \
      -p "${CHROME_SHA}" -p "${REWRITTEN_PINNED_SHA}" \
      -m "Merge ToT Chrome @ ${CHROME_SHA} + DEPS Blink @ ${PINNED_BLINK_SHA}")"
  
  echo "Pushing the merge commit ${MERGE_COMMIT} to origin/master_pinned"
  git branch -q -f master_pinned "${MERGE_COMMIT}"
  with_backoff git push origin --force master_pinned:refs/heads/master_pinned
else  # N_COMMITS_TO_MERGE > 0
  echo "Nothing to be done"
fi

exit 0
