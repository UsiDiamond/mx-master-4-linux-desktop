#!/usr/bin/env bash
# Build-test the Fedora RPM inside a clean fedora container.
# Source tree is mounted read-only at /src; everything happens under /work.
set -euxo pipefail

NAME=mx-master-4-desktop
VERSION=0.1.0
SPEC=/src/packaging/fedora/${NAME}.spec

dnf -y install rpm-build rpmlint rpmdevtools dnf-plugins-core >/dev/null

rpmdev-setuptree

# --- stage the source into a tarball matching Source0: NAME-VERSION.tar.gz ---
WORK=/work/${NAME}-${VERSION}
mkdir -p "${WORK}"
# Copy the repo (excluding VCS + build/scratch dirs) into the versioned dir.
cp -a /src/. "${WORK}/"
rm -rf "${WORK}/.git" "${WORK}"/overlay/build "${WORK}"/config-ui/build
find "${WORK}" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "${WORK}" -name '*.pyc' -delete 2>/dev/null || true
rm -rf "${WORK}/daemon/.pytest_cache"

tar -C /work -czf ~/rpmbuild/SOURCES/${NAME}-${VERSION}.tar.gz ${NAME}-${VERSION}
cp "${SPEC}" ~/rpmbuild/SPECS/

# --- verify dependency names resolve via dnf --------------------------------
echo "=== DEP RESOLUTION CHECK ==="
for p in cmake ninja-build gcc-c++ extra-cmake-modules qt6-qtbase-devel \
         qt6-qtdeclarative-devel qt6-qtquickcontrols2-devel layer-shell-qt-devel \
         python3 python3-dbus python3-gobject python3-xlib \
         qt6-qtbase qt6-qtdeclarative qt6-qtquickcontrols2 layer-shell-qt \
         qt6-qttools dbus-tools; do
    if dnf -q list --available "$p" >/dev/null 2>&1 || dnf -q list --installed "$p" >/dev/null 2>&1; then
        echo "OK   $p"
    else
        echo "MISS $p"
    fi
done
echo "=== END DEP CHECK ==="

# --- install build deps from the spec ---------------------------------------
dnf -y builddep ~/rpmbuild/SPECS/${NAME}.spec

# --- build the binary RPM ---------------------------------------------------
rpmbuild -bb ~/rpmbuild/SPECS/${NAME}.spec

echo "=== PRODUCED RPMS ==="
find ~/rpmbuild/RPMS -name '*.rpm' -print

echo "=== RPMLINT ==="
rpmlint ~/rpmbuild/SPECS/${NAME}.spec ~/rpmbuild/RPMS/*/*.rpm || true

echo "=== RPM CONTENTS ==="
rpm -qlp ~/rpmbuild/RPMS/*/*.rpm | sort
echo "=== RPM REQUIRES ==="
rpm -qp --requires ~/rpmbuild/RPMS/*/*.rpm | sort
