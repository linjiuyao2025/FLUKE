#!/usr/bin/env bash
set -euo pipefail

# Keep the MinGW compiler and pkgconf explicit. pkgconf otherwise expands
# the installed .pc prefix to a Windows path containing the workspace space.
export MSYSTEM=MINGW64
export PATH=/mingw64/bin:/usr/bin:$PATH
export PKG_CONFIG_LIBDIR=/mingw64/lib/pkgconfig:/mingw64/share/pkgconfig
export PKG_CONFIG_DONT_DEFINE_PREFIX=1

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/source/unpacked/ffmpeg/FFmpeg-51c4a23d74"
BUILD="$ROOT/build"
PREFIX="$ROOT/staging"

test -x "$SOURCE/configure"
mkdir -p "$BUILD" "$PREFIX/bin"
cd "$BUILD"

"$SOURCE/configure" \
  --prefix="$PREFIX" \
  --bindir="$PREFIX/bin" \
  --libdir="$PREFIX/bin" \
  --shlibdir="$PREFIX/bin" \
  --pkg-config=pkg-config \
  --cc=gcc \
  --cxx=g++ \
  --ar=ar \
  --ranlib=ranlib \
  --nm=nm \
  --windres=windres \
  --target-os=mingw32 \
  --arch=x86_64 \
  --enable-cross-compile \
  --disable-autodetect \
  --disable-gpl \
  --disable-nonfree \
  --disable-libzvbi \
  --enable-version3 \
  --enable-shared \
  --disable-static \
  --enable-pthreads \
  --disable-w32threads \
  --enable-d3d11va \
  --enable-mediafoundation \
  --enable-libmp3lame \
  --enable-libopus \
  --enable-libvorbis \
  --enable-libvpx \
  --disable-debug \
  2>&1 | tee "$ROOT/configure.log"

make -j"$(nproc)" ffmpeg.exe ffprobe.exe 2>&1 | tee "$ROOT/make.log"
make install 2>&1 | tee "$ROOT/install.log"

"$PREFIX/bin/ffmpeg.exe" -version > "$ROOT/version.txt" 2>&1
"$PREFIX/bin/ffmpeg.exe" -buildconf > "$ROOT/buildconf.txt" 2>&1
"$PREFIX/bin/ffmpeg.exe" -hide_banner -encoders > "$ROOT/encoders.txt" 2>&1
"$PREFIX/bin/ffmpeg.exe" -hide_banner -muxers > "$ROOT/muxers.txt" 2>&1
printf 'FFmpeg build and install completed: %s\n' "$PREFIX/bin/ffmpeg.exe"
