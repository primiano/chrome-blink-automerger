# Chrome + Blink merge script

This is a (set of) script(s) to handle the rewrite of the Blink repo and its
merge into chromium in a repeatable and performant way (~20-30 min).


How to run:
-----------
Create an empty folder, possibly under tmpfs. The rewrite takes ~15 GB of space
(to clone chromium + blink and create the merge repo).
Make sure you have enough swap if using tmpfs (which is warmly suggested).

**Running the merge**

    mount -t tmpfs none /mnt -o noatime,size=25G
    cd /mnt  # or any other empty folder
    # edit config.py if necessary to adjust the branches list.
    ~/chrome-blink-automerger/history_rewrite_scripts/chromium_blink_merge.py

This will mirror the {chromium,blink} repos in /mnt/{chromium,blink}.git and
generate a merged repo in /mnt/chrome-blink-merge.git.
Note, for performances reasons the merged repo has `alternates` references to
the chrome and blink repos. Do not move or remove any of the repos after the
merge or you will have to repeat operation (or be enough of a git surgeon to fix
it).

Once the merge is complete it will create a repo in `chrome-blink-merge.git`.
This repo will be identical to the original `chromium.git`, modulo the branches
`master` and `branch-heads/(whatever defined in config.py)`.

Those branches will have the same chromium history to the original ones
(read: fast-forwardable) but with a merge commit on top.
The merge commit will bring in, as 2nd parent, the history of blink,
rewritten as described in the section "anatomy of the blink history rewrite".

    ----------------------------------------------
                 RESULT OF THE MERGE
    ----------------------------------------------
    refs/heads/master          + refs/heads/master                -> 012345678abcdef
    refs/branch-heads/2214     + refs/branch-heads/chromium/2214  -> abcdef012345678
    refs/branch-heads/2272     + refs/branch-heads/chromium/2272  -> abcdefabcdef012

At this point, after having verified that the merge is actually sensible,
do the following:

    cd /mnt/chrome-blink-merge.git
    git fsck
    REMOTE="https://chromium.googlesource.com/chromium/src.git"
    git push "$REMOTE" refs/heads/master refs/branch-heads/2214 refs/branch-heads/2272

Should the git server refuse the push (because of the excessive size), you can
use [git-gradual-push](https://github.com/primiano/git-tools/blob/master/git-gradual-push)
to push warm up the rewritten blink history as follows:

    git-gradual-push "$REMOTE" HEAD^2 refs/ignore/blink_tmp


Anatomy of the blink history rewrite:
-------------------------------------
The git magic inside `blink_rewriter.py` (which is invoked automatically by
`chromium_blink_merge.py`) does the following:

     for each commit in $BRANCH_BEING_REWRITTEN:
        move the root tree under third_party/WebKit/
        remove /LayoutTests/**.png (except last commit)


Anatomy of the merge in master:
-------------------------------
    Chromium master:

          |-base                    |-base
          |-content                 |-content
          |-...                     |-...
          |-.gitignore              |-.gitignore (NO third_party/WebKit)
          |-DEPS (webkit @ SHA)     |-DEPS (NO WebKit)
          |                         |-third_party/WebKit
         /                         /
      [ #C1 ] ... < [ #C1000 ] < [ #C1001 ] <-+ [ #MERGE_COMMIT ]
                                             /            \
                                            /             |-base
                                           /              |-content
    Blink master (rewritten)              V               |-...
      [ #B1 ] ...    <  [ #B500 ]  < [ #B501]             |-third_party
                           \                                |-WebKit
                            |-third_party                     |-Source
                              |-WebKit                        |-LayoutTests
                                |-Source                      |-...
                                |-LayoutTests
                                |-...

Other than creating the merge commit with the rewritten blink history,
the merge script does also:

  - Remove third_party/WebKit from .gitignore
  - Remove blink references from DEPS (see `deps_cleanup.py`)



Anatomy of the merge in a release branch:
-----------------------------------------
Same steps (including .gitignore and DEPS) of master, but on release branches.

    Chromium

    [ #C1 ] ... < [ #C900 ] < [ #C901 ] < ... < [ #C1000 ]  (master)
                       \
                        \
                         \[ #C_M41_1 ] < ... < [ #C_M41_2 ]  (branch-heads/2214 pre-merge)
                                                   ^
                                                    \
                                                     \
                                                      [ #MERGE_COMMIT ] (branch-heads/2214 post merge)
                                                     /
    Blink                                           /
                                                    V
                         /[ #B_M41_1 ] < ... < [ #B_M41_2 ]  (branch-heads/chromium/2214)
                        /
                       /
    [ #B1 ] ... < [ #B200 ] < [ #C201 ] < ... < [ #C500 ]  (master)


