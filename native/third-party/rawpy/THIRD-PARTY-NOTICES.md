# RAW image conversion notices

FLUKE uses `rawpy` 0.27.1 to decode supported camera RAW files into an RGB image before writing the selected output format. `rawpy` is distributed under the MIT License. Its Windows wheel includes the LibRaw runtime library as a separate DLL.

`rawpy` depends on NumPy. Python 3.10 and 3.11 environments pin NumPy 2.2.6; Python 3.12 and newer environments pin NumPy 2.5.3. FLUKE bundles the license texts for both supported wheels, including their bundled component notices, under `licenses/numpy-2.2.6/` and `licenses/numpy/`.

LibRaw is available under LGPL-2.1 or CDDL-1.0. The corresponding license texts are in `licenses/libraw/`. The matching `rawpy` 0.27.1 source distribution, including the LibRaw source used by the release, is included at `source/rawpy-0.27.1.tar.gz` so recipients can inspect, rebuild, or replace the separately loaded LibRaw DLL. The application does not modify rawpy or LibRaw.

The installed desktop package retains these files under `_internal/licenses/rawpy/`. The LibRaw DLL remains a separate file in the PyInstaller onedir package.

## Upstream sources

- [rawpy 0.27.1](https://github.com/letmaik/rawpy/tree/v0.27.1)
- [LibRaw](https://github.com/LibRaw/LibRaw)
- [NumPy](https://github.com/numpy/numpy)
