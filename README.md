#!/bin/bash
# Script d'installation hors-ligne de Robot Framework + SikuliLibrary sur Ubuntu 18.04

set -e

echo "== Début de l'installation =="

# Récupérer le dossier de travail
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORKDIR"

# --- Java BellSoft JDK 11 ---
echo ">> Installation de Java (BellSoft JDK 11)..."
dpkg -i ./bellsoft-jdk11.0.26+9-linux-amd64-full.deb

JAVA_HOME="/usr/lib/jvm/bellsoft-jdk11.0.26+9"

# Ajouter JAVA_HOME et PATH au bashrc utilisateur
USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)
if [ -z "$USER_HOME" ]; then USER_HOME="$HOME"; fi

echo "export JAVA_HOME=$JAVA_HOME" >> "$USER_HOME/.bashrc"
echo 'export PATH=$PATH:$JAVA_HOME/bin' >> "$USER_HOME/.bashrc"

export JAVA_HOME="$JAVA_HOME"
export PATH="$PATH:$JAVA_HOME/bin"

# --- Apache Ant ---
echo ">> Installation d'Apache Ant..."
ANT_ARCHIVE=$(ls apache-ant-*-bin.tar.gz)
tar -xzf "$ANT_ARCHIVE" -C /opt
ANT_DIR=$(tar -tf "$ANT_ARCHIVE" | head -n 1 | cut -d/ -f1)
mv "/opt/$ANT_DIR" /opt/ant

echo "export ANT_HOME=/opt/ant" >> "$USER_HOME/.bashrc"
echo 'export PATH=$PATH:$ANT_HOME/bin' >> "$USER_HOME/.bashrc"
export ANT_HOME=/opt/ant
export PATH=$PATH:$ANT_HOME/bin

# --- CMake ---
echo ">> Installation de CMake..."
tar -xzf cmake-*.tar.gz -C /opt
CMAKE_DIR=$(tar -tf cmake-*.tar.gz | head -n 1 | cut -d/ -f1)
ln -s /opt/$CMAKE_DIR/bin/* /usr/local/bin/

# --- Autotools ---
echo ">> Installation des outils de build (autotools)..."
for archive in m4.tar.gz autoconf-*.tar.gz automake-*.tar.gz libtool.tar.gz pkg-config.tar.gz; do
  DIR=$(tar -xzf "$archive" -C /tmp && tar -tf "$archive" | head -n1 | cut -d/ -f1)
  cd /tmp/"$DIR"
  ./configure && make -j$(nproc) && make install
done
ldconfig

# --- Leptonica ---
echo ">> Compilation de Leptonica..."
tar -xzf leptonica.tar.gz -C /tmp
cd /tmp/leptonica*
./configure && make -j$(nproc) && make install
ldconfig

# --- Tesseract ---
echo ">> Compilation de Tesseract..."
tar -xzf tesseract.tar.gaz -C /tmp
cd /tmp/tesseract*
PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure
make -j$(nproc) && make install
ldconfig

# --- OpenCV ---
echo ">> Compilation d'OpenCV..."
tar -xzf 0pencv.tar.gz -C /tmp
cd /tmp/opencv*
mkdir -p build && cd build
cmake .. -DBUILD_SHARED_LIBS=ON -DBUILD_opencv_java=ON
make -j$(nproc) && make install
ldconfig

# Créer lien libopencv_java.so si besoin
OPENCV_JAVA=$(find /usr/local -name "libopencv_java*.so" | head -n1)
ln -sf "$OPENCV_JAVA" /usr/local/lib/libopencv_java.so || true

# --- pip et dépendances Python ---
echo ">> Installation des paquets Python..."
pip3 install --no-index --find-links="$WORKDIR" pip-21.whl
pip3 install --no-index --find-links="$WORKDIR" setuptools.whl
pip3 install --no-index --find-links="$WORKDIR" pycparser.whl
pip3 install --no-index --find-links="$WORKDIR" cffi*.whl
pip3 install --no-index --find-links="$WORKDIR" bcrypt*.whl
pip3 install --no-index --find-links="$WORKDIR" cryptography*.whl
pip3 install --no-index --find-links="$WORKDIR" pyNacl*.whl
pip3 install --no-index --find-links="$WORKDIR" paramiko*.whl
pip3 install --no-index --find-links="$WORKDIR" scp*.whl
pip3 install --no-index --find-links="$WORKDIR" JPype1*.whl
pip3 install --no-index --find-links="$WORKDIR" robotframework*.whl
pip3 install --no-index --find-links="$WORKDIR" robotframwork_sikulilibrary.whl

# --- Configuration SikuliLibrary.jar ---
echo ">> Placement du SikuliLibrary.jar Linux..."
SIKULI_PKG=$(python3 -c "import SikuliLibrary, os; print(os.path.dirname(SikuliLibrary.__file__))")
cp SikuliLibrary.jar "$SIKULI_PKG/lib/"

# --- Fin ---
echo "== Installation terminée =="
echo "Reconnectez-vous ou exécutez : source ~/.bashrc"
