# Copyright 2015 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A tty-aware class to calculate and print ETA for arbitrary jobs."""

import sys
import time


class ETA(object):
  def __init__(self, num_jobs_expected, unit=''):
    self.tstart = time.time()
    self.tprint = 0
    self.checkpoint_time = self.tstart
    self.total = num_jobs_expected
    self.done = 0
    self.checkpoint_done = 0
    self.done_since_checkpoint = 0
    self.unit = unit

  @staticmethod
  def TimeToStr(seconds):
    tgmt = time.gmtime(seconds)
    return time.strftime('%Hh:%Mm:%Ss', tgmt)

  def job_completed(self, num_jobs_completed=1):
    self.done += num_jobs_completed
    now = time.time()
    if sys.stdout.isatty():
      if self.done >= self.total or (now - self.tprint) > 0.5:
        self.tprint = now
        done_since_checkpoint = self.done - self.checkpoint_done
        compl_rate = (now - self.checkpoint_time) / done_since_checkpoint
        eta = ETA.TimeToStr((self.total - self.done) * compl_rate)
        print '\r%d / %d %s (%.1f %s/sec), ETA: %s      ' % (
            self.done,
            self.total,
            self.unit, 1 / compl_rate if compl_rate else 0,
            self.unit,
            eta),
        sys.stdout.flush()
      # Keep a window of the last 5 s. for ETA calculation.
      if now - self.checkpoint_time > 5:
        self.checkpoint_done = self.done
        self.checkpoint_time = now

    # Final completion message
    if self.done >= self.total:
      elapsed = time.time() - self.tstart
      if sys.stdout.isatty():
        print '\r%120s\r' % '',  # Clear the current line.
      print 'Rewrote %d %s in %s (%.1f %s/sec)' % (self.done, self.unit,
          ETA.TimeToStr(elapsed), self.done / elapsed, self.unit)
