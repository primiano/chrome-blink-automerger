#!/bin/bash
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

# This script must be self-contained, as it is pushed standalone during the
# vm creation.

mkdir -p /automerger

# Create the automerger user if it doesn't exist.
getent passwd automerger &>/dev/null || {
  adduser -q automerger --home /automerger --gecos automerger --disabled-login
}

# Allow the automerger user to run commands as unpriviledged user.
grep -q automerger /etc/sudoers || {
  echo 'automerger ALL=(nobody) NOPASSWD: ALL' >> /etc/sudoers
}

chown automerger:automerger /automerger
chmod 755 /automerger

apt-get update
apt-get upgrade -y

# Install git from wheezy-backports, the default one is ancient (1.7).
apt-get install -y -t wheezy-backports git git-core curl python-zdaemon less \
                      vim nginx

# Write the "automerger" command to /usr/local/bin.
cat >/usr/local/bin/automerger <<"EOF"
#!/bin/bash
if [ `whoami` == automerger ]; then
  SUDO=""
else
  SUDO="sudo sudo -u automerger "
fi
$SUDO zdaemon -C /automerger/.zdaemon.conf "$@"
EOF
chmod +x /usr/local/bin/automerger

# on_ac_power doesn't work on the vm and causes git gc --auto to never be run;
# replace it with a symlink to true since we know the vm is never on battery.
dpkg-divert --local --rename --add /sbin/on_ac_power
ln -sf /bin/true /sbin/on_ac_power

dpkg-divert /etc/nginx/sites-enabled/default
cat >/etc/nginx/sites-enabled/default <<"EOF"
  server {
    listen 80 default_server;
    listen [::]:80 default_server ipv6only=on;
    root /automerger;
    server_name localhost;
    location / {
      try_files $uri $uri/ =404;
      index automerger.log;
      autoindex on;
    }
    types {
      text/plain txt log;
    }
  }
EOF
service nginx restart

################################################################################
# The remainder of the script is run as the automerger user using sudo.        #
################################################################################

su -c "$(cat <<"SUDOEOF"

set -e
cd ~

AUTOMERGER_REPO="$(curl -f -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/AUTOMERGER_REPO")"

AUTOMERGER_BRANCH="$(curl -f -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/AUTOMERGER_BRANCH")"

NETRC="$(curl -f -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/netrc")"
if [ $? == 0 ]; then
  echo "${NETRC}" > ~/.netrc
  chmod 600  ~/.netrc
fi

# Stop the automerger if it's already running.
automerger stop &>/dev/null || true

# Set git settings.
git config --global core.deltaBaseCacheLimit 128M

# Fetch and run the automerger scripts.
AUTOMERGER_BIN=/automerger/bin
[ -d "${AUTOMERGER_BIN}" ] || {
  git clone "${AUTOMERGER_REPO}" --branch "${AUTOMERGER_BRANCH}" \
      --single-branch "${AUTOMERGER_BIN}"
}
git -C "${AUTOMERGER_BIN}" fetch -q origin
git -C "${AUTOMERGER_BIN}" reset -q --hard origin/master
git -C "${AUTOMERGER_BIN}" clean -qdf

# Fetch and run the git authentication daemon.
# GCOMPUTE_TOOLS=/automerger/gcompute-tools
# [ -d "${GCOMPUTE_TOOLS}" ] || {
#   git clone https://gerrit.googlesource.com/gcompute-tools "${GCOMPUTE_TOOLS}"
# }
# git -C "${GCOMPUTE_TOOLS}" fetch -q origin
# git -C "${GCOMPUTE_TOOLS}" reset -q --hard origin/master
# git -C "${GCOMPUTE_TOOLS}" clean -qdf
# killall git-cookie-authdaemon &>/dev/null || true
# "${GCOMPUTE_TOOLS}/git-cookie-authdaemon"  # TODO check here

# Create zdaemon config file for automerger service.
cat >/automerger/.zdaemon.conf <<"EOF"
<runner>
  program /automerger/bin/automerger_loop.sh
  directory /automerger/
  socket-name /automerger/automerger.zdsock
  transcript /automerger/automerger.log
  logfile /automerger/automerger.log
</runner>
<environment>
  LANG C
  LC_ALL C
  HOME /automerger
  PATH /usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
</environment>
EOF

# Start automerger service.
touch /automerger/automerger.log
chmod 644 /automerger/automerger.log
echo > /automerger/automerger.log
automerger start

SUDOEOF
)" automerger
