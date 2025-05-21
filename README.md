#!/bin/bash
# Installation hors-ligne de Robot Framework + SikuliLibrary avec toutes les dépendances

set -e

echo "=== Début de l'installation hors-ligne ==="

# --- Détection du chemin utilisateur ---
UTILISATEUR="${SUDO_USER:-$USER}"
HOME_UTILISATEUR=$(eval echo "~$UTILISATEUR")

# --- Chemin du dossier où sont tous les fichiers ---
WORKDIR="$(cd "$(dirname "$0")" && pwd)"
cd "$WORKDIR"

# === 1. Java (BellSoft JDK) ===
if ! command -v java &>/dev/null || ! java -version 2>&1 | grep -q "11.*BellSoft"; then
    echo "[+] Installation de Java (BellSoft JDK)..."
    dpkg -i ./bellsoft-jdk11.0.26+9-linux-amd64-full.deb
    echo 'export JAVA_HOME=/usr/lib/jvm/bellsoft-jdk11.0.26+9' >> "$HOME_UTILISATEUR/.bashrc"
    echo 'export PATH=$PATH:$JAVA_HOME/bin' >> "$HOME_UTILISATEUR/.bashrc"
    export JAVA_HOME=/usr/lib/jvm/bellsoft-jdk11.0.26+9
    export PATH=$PATH:$JAVA_HOME/bin
else
    echo "[=] Java déjà installé."
fi

# === 2. Apache Ant ===
if ! command -v ant &>/dev/null; then
    echo "[+] Installation d'Apache Ant..."
    tar -xzf apache-ant-*.tar.gz -C /opt
    ANT_DIR=$(tar -tf apache-ant-*.tar.gz | head -1 | cut -d/ -f1)
    mv "/opt/$ANT_DIR" /opt/ant
    echo "export ANT_HOME=/opt/ant" >> "$HOME_UTILISATEUR/.bashrc"
    echo 'export PATH=$PATH:$ANT_HOME/bin' >> "$HOME_UTILISATEUR/.bashrc"
    export ANT_HOME=/opt/ant
    export PATH=$PATH:$ANT_HOME/bin
else
    echo "[=] Apache Ant déjà installé."
fi

# === 3. CMake ===
if ! command -v cmake &>/dev/null; then
    echo "[+] Installation de CMake..."
    tar -xzf cmake-*.tar.gz -C /opt
    CMAKE_DIR=$(tar -tf cmake-*.tar.gz | head -n1 | cut -d/ -f1)
    ln -sf /opt/$CMAKE_DIR/bin/* /usr/local/bin/
else
    echo "[=] CMake déjà installé."
fi

# === 4. Autotools ===
install_from_tar() {
    local archive=$1
    local name=$(tar -tf "$archive" | head -1 | cut -d/ -f1)
    if [ ! -d "/usr/local/include/$name" ] && [ ! -f "/usr/local/bin/$name" ]; then
        echo "[+] Compilation et installation de $name..."
        tar -xzf "$archive" -C /tmp
        cd /tmp/"$name"
        ./configure && make -j$(nproc) && make install
        cd "$WORKDIR"
    else
        echo "[=] $name déjà installé."
    fi
}

install_from_tar m4.tar.gz
install_from_tar autoconf-*.tar.gz
install_from_tar automake-*.tar.gz
install_from_tar libtool.tar.gz
install_from_tar pkg-config.tar.gz

ldconfig

# === 5. Leptonica ===
if ! ldconfig -p | grep -q liblept; then
    echo "[+] Compilation de Leptonica..."
    tar -xzf leptonica.tar.gz -C /tmp
    cd /tmp/leptonica*
    ./configure && make -j$(nproc) && make install
    cd "$WORKDIR"
    ldconfig
else
    echo "[=] Leptonica déjà installée."
fi

# === 6. Tesseract ===
if ! command -v tesseract &>/dev/null; then
    echo "[+] Compilation de Tesseract..."
    tar -xzf tesseract.tar.gaz -C /tmp
    cd /tmp/tesseract*
    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure
    make -j$(nproc) && make install
    cd "$WORKDIR"
    ldconfig
else
    echo "[=] Tesseract déjà installé."
fi

# === 7. OpenCV ===
if ! ldconfig -p | grep -q libopencv_core; then
    echo "[+] Compilation d'OpenCV..."
    tar -xzf 0pencv.tar.gz -C /tmp
    cd /tmp/opencv*
    mkdir -p build && cd build
    cmake .. -DBUILD_SHARED_LIBS=ON -DBUILD_opencv_java=ON -DBUILD_EXAMPLES=OFF
    make -j$(nproc) && make install
    cd "$WORKDIR"
    ldconfig
else
    echo "[=] OpenCV déjà installé."
fi

# Créer lien générique vers libopencv_java.so si nécessaire
OPENCV_JAVA_SO=$(find /usr/local -name "libopencv_java*.so" | head -n1)
if [ -n "$OPENCV_JAVA_SO" ]; then
    ln -sf "$OPENCV_JAVA_SO" /usr/local/lib/libopencv_java.so
fi

# === 8. pip et bibliothèques Python ===
if ! command -v pip3 &>/dev/null; then
    echo "[+] Installation de pip..."
    python3 pip-21.whl/pip install pip-21.whl
fi

install_whl_if_needed() {
    local name="$1"
    if ! python3 -m pip show "$name" &>/dev/null; then
        echo "[+] Installation de $name..."
        pip3 install --no-index --find-links="$WORKDIR" "$name"*.whl
    else
        echo "[=] $name déjà installé."
    fi
}

install_whl_if_needed pycparser
install_whl_if_needed cffi
install_whl_if_needed bcrypt
install_whl_if_needed cryptography
install_whl_if_needed pyNaCl
install_whl_if_needed paramiko
install_whl_if_needed scp
install_whl_if_needed JPype1
install_whl_if_needed robotframework
install_whl_if_needed robotframwork_sikulilibrary
install_whl_if_needed setuptools

# === 9. Configuration de SikuliLibrary.jar ===
echo "[+] Configuration de SikuliLibrary.jar..."
SIKULI_DIR=$(python3 -c "import SikuliLibrary, os; print(os.path.dirname(SikuliLibrary.__file__))")
if [ -d "$SIKULI_DIR/lib" ] && [ -f "$WORKDIR/SikuliLibrary.jar" ]; then
    cp "$WORKDIR/SikuliLibrary.jar" "$SIKULI_DIR/lib/SikuliLibrary.jar"
    echo "[=] JAR copié dans $SIKULI_DIR/lib/"
else
    echo "[!] SikuliLibrary.jar non copié : fichier ou répertoire manquant."
fi

echo "=== Installation terminée ==="
echo "Relance ta session ou fais : source ~/.bashrc"
