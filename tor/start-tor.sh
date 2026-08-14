#!/bin/bash

if [ -z "$TOR_PASSWORD" ]; then
  echo "ERROR: env variable TOR_PASSWORD not set!"
  exit 1
fi
HASH=$(tor --hash-password "$TOR_PASSWORD" | tail -n 1)

cp /etc/tor/torrc /tmp/torrc.active
echo "HashedControlPassword $HASH" >> /tmp/torrc.active
exec tor -f /tmp/torrc.active