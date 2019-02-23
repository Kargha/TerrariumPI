#!/bin/bash
BASEDIR=$(dirname $(readlink -nf $0))
SCRIPT_USER=`who -m | awk '{print $1}'`
if [ "" == "${SCRIPT_USER}" ]; then
  SCRIPT_USER="pi"
fi
SCRIPT_USER_ID=`id -u ${SCRIPT_USER}`
VERSION=`grep ^version defaults.cfg | cut -d' ' -f 3`
WHOAMI=`whoami`
PYTHON=2
PYTHON_VERSION=$1
if [ "${PYTHON_VERSION}" == "3" ]; then
  PYTHON=3
fi
LOGFILE="${BASEDIR}/log/terrariumpi.log"
ACCESSLOGFILE="${BASEDIR}/log/terrariumpi.access.log"
TMPFS="/run/user/${SCRIPT_USER_ID}"
INSTALLER_TITLE="TerrariumPI v. ${VERSION} (Python${PYTHON})"

if [ "${WHOAMI}" != "root" ]; then
  echo "Start TerrariumPI installation as user root"
  echo "sudo ./install.sh"
  exit 0
fi

#set -e

# Install dialog for further installation
if ! hash whiptail 2>/dev/null; then
  aptitude -y install whiptail
fi

clear

whiptail --backtitle "${INSTALLER_TITLE}" --title " TerrariumPI Installer " --yesno "TerrariumPI is going to be installed to run with user '${SCRIPT_USER}'. If this is not the right user stop the installation now!\n\nDo you want to continue?" 0 60

case $? in
  1|255) whiptail --backtitle "${INSTALLER_TITLE}"  --title " TerrariumPI Installer " --msgbox "TerrariumPI installation is aborted" 0 60
         exit 0
  ;;
esac

# Clean up first
whiptail --backtitle "${INSTALLER_TITLE}" --title " TerrariumPI Installer " --yesno "TerrariumPI is going to remove not needed programs in order to free up diskspace and make future updates faster. All desktop software will be removed.\n\nDo you want to remove not needed programs?" 0 0

case $? in
  0) whiptail --backtitle "${INSTALLER_TITLE}"  --title " TerrariumPI Installer " --infobox "TerrariumPI is removing not needed programs" 0 0

     debconf-apt-progress -- apt-get -y remove wolfram-engine sonic-pi oracle-java8-jdk desktop-base gnome-desktop3-data libgnome-desktop-3-10 epiphany-browser-data epiphany-browser nuscratch scratch wiringpi "^libreoffice.*"
     debconf-apt-progress -- apt-get -y autoremove
  ;;
esac

# Remove previous python 2.X packages to make sure pip installed libraries are used
debconf-apt-progress -- apt-get -y remove owhttpd owftpd python-gpiozero python-dateutil python-imaging python-ow python-picamera python-pigpio python-psutil python-requests python-rpi.gpio

# Install required packages to get the terrarium software running
PYTHON_LIBS=""
if [ $PYTHON -eq 2 ]; then
  PYTHON_LIBS="python-pip python-dev python-mediainfodll python-smbus python-pil python-opencv python-numpy python-lxml"
elif [ $PYTHON -eq 3 ]; then
  PYTHON_LIBS="python3-pip python3-dev python3-mediainfodll python3-smbus python3-pil python3-numpy python3-lxml"
fi

debconf-apt-progress -- apt-get -y update
debconf-apt-progress -- apt-get -y full-upgrade
debconf-apt-progress -- apt-get -y install libftdi1 screen git subversion watchdog build-essential i2c-tools pigpio owserver sqlite3 vlc-nox ffmpeg libfreetype6-dev libjpeg-dev libasound2-dev sispmctl lshw libffi-dev ntp libglib2.0-dev rng-tools libcblas3 libatlas3-base libjasper1 libgstreamer0.10-0 libgstreamer1.0-0 libilmbase12 libopenexr22 libgtk-3-0 libxml2-dev libxslt1-dev python-twisted $PYTHON_LIBS

# Set the timezone
dpkg-reconfigure tzdata


# Basic config:
# Enable 1Wire en I2C during boot
if [ -f /boot/config.txt ]; then

  if [ `grep -ic "#dtparam=i2c_arm=on" /boot/config.txt` -eq 1 ]; then
    sed -i.bak 's/^#dtparam=i2c_arm=on/dtparam=i2c_arm=on/' /boot/config.txt
  fi
  if [ `grep -ic "dtparam=i2c_arm=on" /boot/config.txt` -eq 0 ]; then
    echo "dtparam=i2c_arm=on" >> /boot/config.txt
  fi

  if [ `grep -ic "dtoverlay=w1-gpio" /boot/config.txt` -eq 0 ]; then
    echo "dtoverlay=w1-gpio" >> /boot/config.txt
  fi

  # Enable camera
  if [ `grep -ic "gpu_mem=" /boot/config.txt` -eq 0 ]; then
    echo "gpu_mem=128" >> /boot/config.txt
  fi

fi

# Create needed groups
groupadd -f dialout 2> /dev/null
groupadd -f sispmctl 2> /dev/null
groupadd -f gpio 2> /dev/null
# Add user to all groupds
usermod -a -G dialout,sispmctl,gpio ${SCRIPT_USER} 2> /dev/null


# Docu https://pylibftdi.readthedocs.io/
# Make sure that the normal Pi user can read and write to the usb driver
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6001", GROUP="dialout", MODE="0660"' > /etc/udev/rules.d/99-libftdi.rules
echo 'SUBSYSTEMS=="usb", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6014", GROUP="dialout", MODE="0660"' >> /etc/udev/rules.d/99-libftdi.rules

# https://pypi.python.org/pypi/pysispm
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="fd10", GROUP="sispmctl", MODE="660"' > /etc/udev/rules.d/60-sispmctl.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="fd11", GROUP="sispmctl", MODE="660"' >> /etc/udev/rules.d/60-sispmctl.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="fd12", GROUP="sispmctl", MODE="660"' >> /etc/udev/rules.d/60-sispmctl.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="fd13", GROUP="sispmctl", MODE="660"' >> /etc/udev/rules.d/60-sispmctl.rules
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="fd15", GROUP="sispmctl", MODE="660"' >> /etc/udev/rules.d/60-sispmctl.rules

# Reload udev controll
udevadm control --reload-rules

# Install 1 Wire I2C stuff
if [ -f /etc/owfs.conf ]; then
  sed -i.bak 's/^server: FAKE = DS18S20,DS2405/#server: FAKE = DS18S20,DS2405/' /etc/owfs.conf

  if [ `grep -ic "server: device=/dev/i2c-1" /etc/owfs.conf` -eq 0 ]; then
    echo "server: device=/dev/i2c-1" >> /etc/owfs.conf
  fi
fi

if [ -f /etc/modprobe.d/raspi-blacklist.conf ]; then
  sed -i.bak 's/^blacklist i2c-bcm2708/#blacklist i2c-bcm2708/' /etc/modprobe.d/raspi-blacklist.conf
fi

if [ -f /etc/modules ]; then
  if [ `grep -ic "i2c-dev" /etc/modules` -eq 0 ]; then
    echo "i2c-dev" >> /etc/modules
  fi
fi

# Make sure pigpiod is started at boot, and that user PI can restart it with sudo command
echo "${SCRIPT_USER} ALL=(ALL) NOPASSWD: /usr/sbin/service pigpiod restart" > /etc/sudoers.d/terrariumpi
systemctl enable pigpiod

# Remove unneeded OWS services
update-rc.d -f owftpd remove
update-rc.d -f owfhttpd remove

PROGRESS=35
# Update submodules if downloaded through tar or zip
(
cd "${BASEDIR}/"
cat <<EOF
XXX
$PROGRESS
Install required software\n\nInstalling base software ...
XXX
EOF


PROGRESS=$((PROGRESS + 5))
cat <<EOF
XXX
$PROGRESS
Install required software\n\nInstalling base software ...
XXX
EOF
git submodule init > /dev/null


PROGRESS=$((PROGRESS + 5))
cat <<EOF
XXX
$PROGRESS
Install required software\n\nInstalling base software ...
XXX
EOF
git submodule update > /dev/null
cd "${BASEDIR}/.."

PIP_MODULES="python-dateutil rpi.gpio psutil picamera pigpio requests gpiozero gevent untangle uptime bottle bottle_websocket pylibftdi pyalsaaudio pyserial python-twitter python-pushover requests[socks] Adafruit_DHT Adafruit_SHT31 luma.oled bluepy pywemo pyownet emails"
if [ $PYTHON -eq 3 ]; then
  PIP_MODULES="${PIP_MODULES} opencv-python-headless meross_iot"
fi
NUMBER_OF_MODULES=($PIP_MODULES)
NUMBER_OF_MODULES=${#NUMBER_OF_MODULES[@]}
MODULE_COUNTER=1
for PIP_MODULE in ${PIP_MODULES}
do
  PROGRESS=$((PROGRESS + 2))
  ATTEMPT=1
  MAX_ATTEMPTS=5
  while [ $ATTEMPT -le $MAX_ATTEMPTS ]
  do

    cat <<EOF
XXX
$PROGRESS
Install required software (some modules will take 5-10 min.)

Installing python${PYTHON} module ${MODULE_COUNTER} out of ${NUMBER_OF_MODULES}: ${PIP_MODULE} (attempt ${ATTEMPT}) ...
XXX
EOF
    if [ $PYTHON -eq 2 ]; then
      pip2 install -q --upgrade ${PIP_MODULE}
    elif [ $PYTHON -eq 3 ]; then
      pip3 install -q --upgrade ${PIP_MODULE}
    fi

    if [ $? -eq 0 ]; then
      # PIP install succeeded normally
      ATTEMPT=$((ATTEMPT + 99))
    else
      # PIP install failure... retry..
      ATTEMPT=$((ATTEMPT + 1))
    fi

  done

  MODULE_COUNTER=$((MODULE_COUNTER + 1))

done

if [ $PYTHON -eq 3 ]; then
  # Remove pip numpy install that comes with an upgrade of another module. Does not work
  # Removing this will fallback to OS default
  pip3 uninstall -y -q numpy
fi

cd "${BASEDIR}"
chown ${SCRIPT_USER}. .
chown ${SCRIPT_USER}. * -Rf

PROGRESS=100
cat <<EOF
XXX
$PROGRESS
Install required software\n\nDone! ...
XXX
EOF

sleep 1
) | whiptail --backtitle "${INSTALLER_TITLE}" --title " TerrariumPI Installer " --gauge "Install required software\n\nInstalling python module ${PIP_MODULE} ..." 0 78 0


# To run this as non-root run the following, https://github.com/marcelrv/miflora, https://github.com/IanHarvey/bluepy/issues/218
if [ $PYTHON -eq 2 ]; then
  setcap 'cap_net_raw,cap_net_admin+eip' /usr/local/lib/python2.7/dist-packages/bluepy/bluepy-helper
elif [ $PYTHON -eq 3 ]; then
  setcap 'cap_net_raw,cap_net_admin+eip' /usr/local/lib/python3.5/dist-packages/bluepy/bluepy-helper
fi

# Move log file to temprorary mount
if grep -qs "${TMPFS} " /proc/mounts; then
  # TMPFS user dir is available....
  if ! [ -h "${LOGFILE}" ]; then
    # There is not a symlink to tmpfs partition
    if [ -f "${LOGFILE}" ]; then
      # There is an existing logfile already. Move it
      mv ${LOGFILE} ${TMPFS}
    fi
    su -c "ln -s ${TMPFS}/terrariumpi.log ${LOGFILE}" -s /bin/bash ${SCRIPT_USER}
  fi

  if ! [ -h "${ACCESSLOGFILE}" ]; then
    # There is not a symlink to tmpfs partition
    if [ -f "${ACCESSLOGFILE}" ]; then
      # There is an existing logfile already. Move it
      mv ${ACCESSLOGFILE} ${TMPFS}
    fi
    su -c "ln -s ${TMPFS}/terrariumpi.access.log ${ACCESSLOGFILE}" -s /bin/bash ${SCRIPT_USER}
  fi
fi

# Make TerrariumPI start during boot
if [ `grep -ic "start.sh" /etc/rc.local` -eq 0 ]; then
  sed -i.bak "s@^exit 0@# Starting TerrariumPI server\n${BASEDIR}/start.sh\n\nexit 0@" /etc/rc.local
fi

# We are done!
sync

whiptail --backtitle "${INSTALLER_TITLE}" --title " TerrariumPI Installer " --yesno "TerrariumPI is installed/upgraded. To make sure that all is working please reboot.\n\nDo you want to reboot now?" 0 60

case $? in
  0)
  for SECONDS in {5..1}
  do
    echo "TerrariumPI installation is rebooting the Raspberry PI in ${SECONDS} seconds..."
    sleep 1
  done
  sync
  reboot
  ;;
esac
