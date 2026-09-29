#!/usr/bin/bash
set -euo pipefail
root="$(cygpath -u "$FLUKE_BUILD_ROOT")"
src="$root/tiff-4.7.2-clean-src"
build="$root/build6-MINGW64-shared"

export CC=gcc CXX=g++ AR=ar RANLIB=ranlib LD=ld LDFLAGS=-L/mingw64/lib
export lt_cv_path_LD=ld lt_cv_path_LDCXX=ld
export CFLAGS="${CFLAGS:-} -fno-strict-aliasing"
export CXXFLAGS="${CXXFLAGS:-} -fno-strict-aliasing"

mkdir -p "$build"
cd "$build"
"$src/configure" \
  --prefix="$MINGW_PREFIX" \
  --build="$MINGW_CHOST" \
  --host="$MINGW_CHOST" \
  --target="$MINGW_CHOST" \
  --disable-static \
  --enable-shared \
  --enable-cxx \
  --disable-jbig \
  --enable-lerc \
  --enable-libdeflate \
  --enable-webp
make -C libtiff -j4 libtiff.la
