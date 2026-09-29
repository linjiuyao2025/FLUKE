# FFmpeg candidate third-party notices

Candidate only. This notice inventory is generated from the pinned source archives; it does not establish installed-app or published-release acceptance.

- FFmpeg 9.0.2-10-g51c4a23d74: LGPL-3.0-or-later. The corresponding source archive and SHA-256 are listed in `source-manifest.json`.
- LAME 3.100: LGPL; upstream `COPYING` and `LICENSE`, source tarball, MSYS2 recipe, and patches are included.
- libvpx 1.17.0: BSD-3-Clause; upstream `LICENSE` and `PATENTS`, source tarball, MSYS2 recipe, and patch are included.
- Opus 1.6.1: BSD-3-Clause; upstream `COPYING`, source tarball, MSYS2 recipe, and patch are included.
- libvorbis 1.3.7: the upstream Xiph `COPYING` text is included with its source tarball and MSYS2 recipe.
- libogg 1.3.6: BSD-3-Clause; upstream `COPYING`, source tarball, MSYS2 recipe, and patch are included.
- MinGW GCC runtime DLLs `libgcc_s_seh-1.dll` and `libstdc++-6.dll`: GPL-3.0-or-later with GCC Runtime Library Exception 3.1; `COPYING3` and `COPYING.RUNTIME` texts, exact GCC source-only archive, recipe, and patches are included.
- MinGW winpthreads runtime DLL `libwinpthread-1.dll`: MIT and BSD-3-Clause-Clear; upstream license text and exact source-only archive, recipe, and patch are included.

The MSYS2 source-only archives contain the exact package recipe, patches, and upstream source archives associated with the package versions selected for this isolated candidate. SHA-256 values for every archive are recorded in `source-manifest.json`.

The build configuration is LGPL shared, disables GPL, nonfree, autodetected components, and libzvbi. The runtime PE dependency closure is recorded separately; Windows system imports remain supplied by Windows.
