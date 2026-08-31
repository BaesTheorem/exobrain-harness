#!/bin/bash
#make by G.R.H

if [ ! -f /usr/bin/mpv ]; then
    echo "Error: The necessary playback files are missing and the program cannot run."
    exit 1
fi
. /mnt/mod/ctrl/configs/functions &>/dev/null 2>&1
progdir=$(cd $(dirname $0); pwd)

ip_addres=$(ip -4 addr show wlan0 | awk '/inet / {print $2}' | cut -d/ -f1)
if [ -z $ip_addres]; then
    mpv $rotate_28 --really-quiet --fs --image-display-duration=3 "${progdir}/res/noconn-${LANG_CUR}.png"
    user_quit
fi
cat<<EOF > "${progdir}/res/ip.srt"
1
00:00:00,000 --> 02:00:00,000
\\\\${ip_addres}, User: root, Pass: root
EOF

case "$HW_MODEL" in
    "RG28xx")
        rm "$0"
        exit 2
    ;;
esac


function enable_samba() {
systemctl enable smbd
systemctl start smbd
systemctl enable nmbd
systemctl start nmbd
}

function disable_samba() {
systemctl stop smbd
systemctl disable smbd
systemctl stop nmbd
systemctl disable nmbd
}


pkill -f mpv
pkill -f evtest
if [ "$(systemctl is-active smbd)" = "inactive" ] || [ "$(systemctl is-active nmbd)" = "inactive" ]; then
    enable_samba
fi


mpv $rotate_28 --really-quiet --fs --image-display-duration=6000 "${progdir}/res/sambatmp-${LANG_CUR}.png" --sub-file="${progdir}/res/ip.srt" &
get_devices

(
     for INPUT_DEVICE in ${INPUT_DEVICES[@]}
     do
     evtest "${INPUT_DEVICE}" 2>&1 &
     done
     wait
) | while read line; do
    case $line in
        (${CONTROLLER_DISCONNECTED})
        echo "Reloading due to ${CONTROLLER_DEVICE} reattach..." 2>&1
        get_devices
        ;;
        (${DEVICE_DISCONNECTED})
        echo "Reloading due to ${DEVICE} reattach..." 2>&1
        get_devices
        ;;
        (${FUNC_KEY_EVENT})
            if [[ "${line}" =~ ${PRESS} ]]; then
                continue
            elif [[ "${line}" =~ ${RELEASE} ]]; then
                pkill -f mpv
                if grep -q "global.samba=0" "/mnt/mod/ctrl/configs/system.cfg"; then
                    disable_samba
                fi
                user_quit
            fi
        ;;
    esac
done
