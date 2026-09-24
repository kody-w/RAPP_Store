#!/bin/sh
set -eu

test "${NODE_TAR_XZ}" = "/opt/node-v20.20.0-linux-x64.tar.xz"
test "${NODE_DIR}" = "/opt/node-v20.20.0-linux-x64"
if [ ! -f /opt/.dock-node-ready ]; then
    test -f "${NODE_TAR_XZ}"
    tar --no-same-owner -xf "${NODE_TAR_XZ}" -C /opt
    test -x "${NODE_DIR}/bin/node"
    touch /opt/.dock-node-ready
fi
test -x "${NODE_DIR}/bin/node"
if [ ! -L /usr/local/bin/node ]; then
    test ! -e /usr/local/bin/node
    ln -s "${NODE_DIR}/bin/node" /usr/local/bin/node
fi
test "$(readlink /usr/local/bin/node)" = "${NODE_DIR}/bin/node"
exec /main
