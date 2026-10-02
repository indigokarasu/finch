#!/usr/bin/env python3
"""Test for the third liveness source in in_use_paths().

The defect (measured 2026-09-30, finch:work scan 1049): a file that a running
process has MEMORY-MAPPED, but which appears in no argv token and in no open
file descriptor, was invisible to in_use_paths(). Both of its two existing
sources miss that shape, and the shape is not exotic -- it is how a loader reads
a large weight without pinning a descriptor: open, mmap, close.

reclaim_candidates() subtracts in_use paths before calling a file reclaimable,
so a file invisible to in_use_paths() is reported as FREE. For a live service's
weight that is the one answer that must never be produced: the delete succeeds,
and the failure does not appear until the next request.

Each case runs against a SYNTHETIC fixture -- a fabricated /proc tree under a
temp directory and a caller-injected proc root -- so the test proves the RULE
rather than this host's /proc, and so a machine with nothing mmapped still
exercises both directions. The negative cases carry the weight: a file named by
NOBODY must not be marked in use, or the fix would simply mark everything live
and disable the reclaim estimate.
"""
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import finch_disk_watch as w  # noqa: E402


def write_proc_tree(root, pids):
    """Fabricate a /proc-shaped tree: root/<pid>/{cmdline,maps,fd/}.

    ``cmdline`` may be given as str or bytes. A real /proc/<pid>/cmdline is
    NUL-SEPARATED, so a fixture written as a single space-joined string
    produces one argv token instead of several and proves nothing about how
    the reader splits it.
    """
    for pid, spec in pids.items():
        pdir = os.path.join(root, str(pid))
        os.makedirs(os.path.join(pdir, "fd"))
        cmdline = spec.get("cmdline", b"")
        if isinstance(cmdline, str):
            cmdline = b"\0".join(t.encode() for t in cmdline.split("\x00"))
        with open(os.path.join(pdir, "cmdline"), "wb") as fh:
            fh.write(cmdline)
        with open(os.path.join(pdir, "maps"), "w") as fh:
            fh.write(spec.get("maps", ""))
        for fd, target in spec.get("fds", {}).items():
            link = os.path.join(pdir, "fd", str(fd))
            if target is None:
                # A real fd link points at an existing path; a dangling one
                # would make realpath() fail the way a closed fd does.
                os.symlink("/dev/null", link)
            else:
                os.symlink(target, link)


MAPS_LINE = "{addr}-{addr} {perms} {off:08x} 00:00 0 \t{path}\n"


class TestMmapLiveness(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.proc = os.path.join(self.dir, "proc")
        os.makedirs(self.proc)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)

    def tearDown(self):
        self.real_glob = w.glob.glob
        self.addCleanup(setattr, w.glob, "glob", self.real_glob)

    def in_use(self, pids):
        """Run in_use_paths() against the synthetic tree, not the real /proc.

        in_use_paths() returns (paths, pids_by_path, sources_by_path) since
        #1101; this helper unwraps the membership set so the existing
        assertions keep testing liveness rather than the container shape.
        """
        return self.provenance(pids)[0]

    def provenance(self, pids):
        """Same walk, but returning the full (paths, pids, sources) triple."""
        write_proc_tree(self.proc, pids)
        w.glob.glob = lambda pat: (
            [os.path.join(self.proc, str(pid)) for pid in pids]
            if pat == "/proc/[0-9]*" else self.real_glob(pat)
        )
        return w.in_use_paths()

    # --- provenance: WHICH pid and WHICH source made the call (#1101) ---

    def test_live_path_carries_the_pid_that_named_it(self):
        """The boolean alone is not auditable; the pid makes it checkable.

        This pass asked `systemctl --user is-active` and read "inactive",
        concluding two weights were free. The unit is a SYSTEM unit. The report
        said nothing that distinguished "free" from "free because you looked in
        the wrong place", so the pid that names the path has to be published.
        """
        paths, by_pid, by_src = self.provenance({4242: {
            "cmdline": "/usr/bin/llama-server\x00-m\x00/models/weight.gguf\x00",
        }})
        self.assertIn("/models/weight.gguf", paths)
        self.assertEqual(by_pid["/models/weight.gguf"], {"4242"})
        self.assertEqual(by_src["/models/weight.gguf"], {"argv"})

    def test_each_source_is_labelled_distinctly(self):
        """argv, maps and fd are three independent reads; they must not merge."""
        _, _, by_src = self.provenance({7: {
            "cmdline": "/usr/bin/llama-server\x00-m\x00/models/a.gguf\x00",
            "maps": MAPS_LINE.format(addr="7f0000000000", perms="r--p",
                                     off=0, path="/models/b.gguf"),
        }})
        self.assertEqual(by_src["/models/a.gguf"], {"argv"})
        self.assertEqual(by_src["/models/b.gguf"], {"maps"})

    def test_unreferenced_path_is_absent_from_the_provenance_maps(self):
        """A free file must carry NO pid -- absence is the auditable form of False."""
        _, by_pid, _ = self.provenance({9: {
            "cmdline": "/usr/bin/unrelated\x00--flag\x00",
        }})
        self.assertNotIn("/models/free.gguf", by_pid)

    # --- the three positive shapes, each of which must be reported in use ---

    def test_mmap_only_file_is_in_use(self):
        """The defect: mapped, named by no argv, held by no fd -- still live."""
        got = self.in_use({100: {
            "cmdline": "/usr/bin/llama-server\x00--port\x008081\x00",
            "maps": MAPS_LINE.format(addr="7f0000000000", perms="r--p",
                                     off=0, path="/models/weight.gguf"),
        }})
        self.assertIn("/models/weight.gguf", got)

    def test_argv_named_file_still_in_use(self):
        """The pre-existing source must keep working alongside the new one."""
        got = self.in_use({100: {
            "cmdline": "/usr/bin/llama-server\x00-m\x00/models/weight.gguf\x00",
        }})
        self.assertIn("/models/weight.gguf", got)

    def test_open_fd_still_in_use(self):
        got = self.in_use({100: {
            "cmdline": "/usr/bin/llama-server\x00",
            "fds": {3: "/models/weight.gguf"},
        }})
        self.assertIn("/models/weight.gguf", got)

    # --- negatives: these prove the fix does not simply mark everything live --

    def test_unreferenced_file_is_not_in_use(self):
        """A file no live process touches must NOT be called in use.

        Without this the fix degenerates: mark every path in use and the
        reclaim estimate reads zero forever, which is a false NEGATIVE in the
        other direction -- it would silently hide a genuine 4 GB reclaim from
        Jared.
        """
        got = self.in_use({100: {
            "cmdline": "/usr/bin/sleep\x00100\x00",
            "maps": MAPS_LINE.format(addr="7f0000000000", perms="r--p",
                                     off=0, path="/usr/lib/libc.so.6"),
        }})
        self.assertNotIn("/models/weight.gguf", got)
        self.assertNotIn("/models/idle.gguf", got)

    def test_anonymous_and_heap_regions_ignored(self):
        """[heap], [stack] and anonymous mappings carry no file and must not
        become paths -- a bare '[' would be a junk entry in the set."""
        got = self.in_use({100: {
            "cmdline": "/usr/bin/sleep\x00100\x00",
            "maps": (
                "55a0-55b0 r-xp 00000000 00:00 0 [heap]\n"
                "7ffd-7fff rw-p 00000000 00:00 0 [stack]\n"
                "7f00-7f01 rw-p 00000000 00:00 0 \n"
            ),
        }})
        self.assertEqual(got, {"/usr/bin/sleep"})

    def test_mapped_deleted_file_keeps_its_path(self):
        """A mapped region whose file was unlinked reads '<path> (deleted)'.

        It can no longer be a reclaim candidate, so the suffix is stripped to
        leave a clean path rather than a path with a marker glued on that would
        never match any candidate on disk.
        """
        got = self.in_use({100: {
            "cmdline": "/usr/bin/sleep\x00100\x00",
            "maps": MAPS_LINE.format(addr="7f0000000000", perms="r--p",
                                     off=0, path="/models/gone.gguf (deleted)"),
        }})
        self.assertIn("/models/gone.gguf", got)
        self.assertNotIn("/models/gone.gguf (deleted)", got)

    def test_unreadable_proc_entry_does_not_abort_the_walk(self):
        """A process vanishing mid-walk is normal, not an error.

        A pid directory with no maps/cmdline at all must yield an empty set
        rather than raise, and must not stop the other pids being read.
        """
        pdir = os.path.join(self.proc, "200")
        os.makedirs(os.path.join(pdir, "fd"))
        with open(os.path.join(pdir, "maps"), "w") as fh:
            fh.write(MAPS_LINE.format(addr="7f0000000000", perms="r--p", off=0,
                                     path="/models/a.gguf"))
        w.glob.glob = lambda pat: (
            [os.path.join(self.proc, "200"), os.path.join(self.proc, "201")]
            if pat == "/proc/[0-9]*" else self.real_glob(pat)
        )
        got = w.in_use_paths()[0]
        self.assertIn("/models/a.gguf", got)


if __name__ == "__main__":
    unittest.main(verbosity=2)
