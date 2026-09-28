#

boot2=$HOME/.boot.sh
if [ -e $boot2 ]; then
    echo "[BOOT] exec .boot.sh"
    exec /bin/bash "$boot2"
else
    echo "[BOOT] exec /bin/bash"
    exec /bin/bash
fi
