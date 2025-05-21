#!/bin/bash
# Script d'installation hors-ligne de Robot Framework + SikuliLibrary sur Ubuntu 18.04
# Assurez-vous que ce script est exécuté en tant que root (par exemple via sudo).
# Tous les fichiers .deb, .whl, .tar.gz nécessaires doivent se trouver dans le même répertoire que ce script.

set -e  # Arrêter le script en cas d'erreur (pour robustesse)

echo "== Début de l'installation hors-ligne de Robot Framework + SikuliLibrary =="

# 0. Vérifier si on est root
if [ "$EUID" -ne 0 ]; then
    echo "Veuillez exécuter ce script en tant que root (sudo)." >&2
    exit 1
fi

# Déterminer le répertoire home de l'utilisateur non-root qui a invoqué sudo (si applicable)
if [ -n "$SUDO_USER" ] && [ "$SUDO_USER" != "root" ]; then
    UTILISATEUR="$SUDO_USER"
else
    UTILISATEUR="$(logname)"  # logname renvoie l'utilisateur connecté
fi
HOME_UTILISATEUR=$(getent passwd "$UTILISATEUR" | cut -d: -f6)
if [ -z "$HOME_UTILISATEUR" ]; then
    HOME_UTILISATEUR="$HOME"  # Au cas où, on utilise $HOME
fi

echo "Utilisateur cible pour les configurations de PATH: $UTILISATEUR (home: $HOME_UTILISATEUR)"

# 1. Installation de Java (OpenJDK 8) via le fichier .deb
echo "-> Installation de Java (OpenJDK)..."
dpkg -i ./*openjdk*8*-jdk*.deb ./*openjdk*8*-jre*.deb 2>/dev/null || dpkg -i ./*openjdk*8*.deb 2>/dev/null
# La commande ci-dessus tente d'installer le JDK 8 (et JRE si séparé). 
# S'il y a des dépendances manquantes, dpkg retournera une erreur. 
# Assurez-vous d'avoir fourni tous les .deb requis pour Java.

# 2. Installation d'Apache Ant
echo "-> Installation d'Apache Ant..."
if ls apache-ant-*.tar.gz &>/dev/null; then
    # Si on a une archive tar.gz pour Ant, on l'extrait
    ANT_ARCHIVE="$(ls apache-ant-*.tar.gz | head -n1)"
    ANT_DIR_NAME="$(tar -tf "$ANT_ARCHIVE" | head -1 | cut -d/ -f1)"
    tar -xzf "$ANT_ARCHIVE" -C /opt
    # On renomme le dossier extrait en /opt/ant pour plus de simplicité
    if [ -d "/opt/$ANT_DIR_NAME" ]; then
        mv "/opt/$ANT_DIR_NAME" /opt/ant
    fi
    # Ajouter Ant au PATH (via .bashrc de l'utilisateur)
    echo "export ANT_HOME=/opt/ant" >> "$HOME_UTILISATEUR/.bashrc"
    echo "export PATH=\$PATH:\$ANT_HOME/bin" >> "$HOME_UTILISATEUR/.bashrc"
    echo "Apache Ant installé dans /opt/ant"
elif ls ant_*.deb &>/dev/null; then
    # Si on dispose d'un paquet .deb pour ant
    dpkg -i ant_*.deb ant-optional_*.deb 2>/dev/null || dpkg -i ant_*.deb
    # (Le paquet ant-optional peut ou non être présent selon la version.)
else
    echo "Fichier d'installation pour Apache Ant introuvable. Veuillez fournir apache-ant-*.tar.gz ou ant*.deb." >&2
    exit 1
fi

# 3. Installation de CMake
echo "-> Installation de CMake..."
if ls cmake-*-linux-x86_64.sh &>/dev/null; then
    CMAKE_SH=$(ls cmake-*-linux-x86_64.sh | head -n1)
    chmod +x "$CMAKE_SH"
    ./"$CMAKE_SH" --skip-license --prefix=/usr/local
    # Le binaire cmake est maintenant dans /usr/local/bin (on suppose que /usr/local/bin est dans PATH)
elif ls cmake_*.deb &>/dev/null; then
    dpkg -i cmake_*.deb
else
    echo "Fichier d'installation pour CMake introuvable. Veuillez fournir cmake-*-linux-x86_64.sh ou cmake*.deb." >&2
    exit 1
fi

# 4. Installation des outils de compilation et autotools
echo "-> Installation des outils de développement (build-essential, autotools)..."
# Installer build-essential si fourni (ce paquet contient gcc, g++, make, etc.)
if ls build-essential*.deb &>/dev/null; then
    dpkg -i build-essential*.deb || true  # on ignore d'éventuelles erreurs ici (on vérifiera individuellement)
fi
# Installer GCC, G++ et Make individuellement si pas couverts par build-essential
if ! command -v gcc &>/dev/null; then
    dpkg -i gcc-*.deb cpp-*.deb || true
fi
if ! command -v g++ &>/dev/null; then
    dpkg -i g++-*.deb || true
fi
if ! command -v make &>/dev/null; then
    dpkg -i make-*.deb || true
fi

# Installer Autoconf, Automake, Libtool, M4, pkg-config
dpkg -i m4_*.deb 2>/dev/null || true   # M4 en premier (prérequis pour Autoconf)
dpkg -i autoconf_*.deb automake_*.deb libtool_*.deb 2>/dev/null || true
dpkg -i pkg-config_*.deb 2>/dev/null || true

# (Les "|| true" empêchent l'arrêt en cas de paquet déjà installé ou dépendance manquante.
# On suppose que toutes les dépendances de ces paquets sont soit satisfaites par le système de base soit fournies.)

# 5. Installation/Compilation de Leptonica
echo "-> Installation de Leptonica..."
if ls leptonica-*.tar.gz &>/dev/null; then
    LEPT_TAR=$(ls leptonica-*.tar.gz | head -n1)
    LEPT_DIR="${LEPT_TAR%.tar.gz}"
    tar -xzf "$LEPT_TAR"
    cd "$LEPT_DIR"
    # Si un script autogen.sh existe (dépend de la distribution du code)
    if [ -f "./autogen.sh" ]; then
        ./autogen.sh
    fi
    ./configure
    make -j$(nproc)
    make install  # Installe dans /usr/local par défaut
    cd ..
    ldconfig       # Mettre à jour le cache des bibliothèques
else
    # Si on a un .deb pour Leptonica (peu probable), on peut l'installer
    dpkg -i liblept*.deb 2>/dev/null || { echo "Fichier pour Leptonica introuvable."; exit 1; }
    ldconfig
fi

# 6. Installation/Compilation de Tesseract OCR
echo "-> Installation de Tesseract OCR..."
if ls tesseract-*.tar.gz &>/dev/null; then
    TESS_TAR=$(ls tesseract-*.tar.gz | head -n1)
    TESS_DIR="${TESS_TAR%.tar.gz}"
    tar -xzf "$TESS_TAR"
    cd "$TESS_DIR"
    if [ -f "./autogen.sh" ]; then
        ./autogen.sh
    fi
    # S'assurer que pkg-config peut trouver Leptonica installé en /usr/local
    export PKG_CONFIG_PATH="/usr/local/lib/pkgconfig:$PKG_CONFIG_PATH"
    ./configure
    make -j$(nproc)
    make install   # Installe libtesseract et l'exécutable tesseract dans /usr/local
    cd ..
    ldconfig
else
    # Installation via paquets .deb si disponibles
    dpkg -i libtesseract*.deb tesseract-ocr*.deb 2>/dev/null || { echo "Fichier pour Tesseract introuvable."; exit 1; }
    ldconfig
fi
# Remarque: Pour l'OCR en français ou autre, pensez à installer les données de langue (ex: tesseract-ocr-fra).

# 7. Installation/Compilation d'OpenCV (y compris modules Java)
echo "-> Installation d'OpenCV (avec support Java)..."
if ls opencv-*.tar.gz &>/dev/null; then
    OPENCV_TAR=$(ls opencv-*.tar.gz | head -n1)
    OPENCV_DIR="${OPENCV_TAR%.tar.gz}"
    tar -xzf "$OPENCV_TAR"
    mkdir -p "$OPENCV_DIR-build" && cd "$OPENCV_DIR-build"
    # Configuration de la construction avec CMake
    cmake "../$OPENCV_DIR" \
        -DBUILD_SHARED_LIBS=ON \
        -DBUILD_opencv_java=ON \
        -DBUILD_JAVA=ON \
        -DINSTALL_PYTHON_EXAMPLES=OFF \
        -DBUILD_EXAMPLES=OFF
    # (Les options ci-dessus activent la compilation des liaisons Java. 
    # On désactive les exemples pour gagner du temps/éviter des dépendances inutiles.)
    make -j$(nproc)
    make install
    cd ..
    ldconfig
else
    # Installation via paquets .deb si fournis
    dpkg -i libopencv*.deb 2>/dev/null || { echo "Fichiers .deb pour OpenCV manquants ou incomplets."; exit 1; }
    ldconfig
fi

# Après installation d'OpenCV, créer un lien symbolique pour la librairie Java d'OpenCV si nécessaire
if [ -e "/usr/local/share/opencv4/java/libopencv_java*.so" ]; then
    # Si on a compilé OpenCV, la librairie Java se trouve typiquement ici
    ln -sf /usr/local/share/opencv4/java/libopencv_java*.so /usr/local/share/opencv4/java/libopencv_java.so || true
elif [ -e "/usr/lib/jni/libopencv_java*.so" ]; then
    # Pour installation via .deb, le .so Java est dans /usr/lib/jni
    ln -sf /usr/lib/jni/libopencv_java*.so /usr/lib/jni/libopencv_java.so || true
fi

# 8. Configuration des variables d'environnement pour Java/Ant
echo "-> Configuration des variables d'environnement (JAVA_HOME, PATH)..."
# Définir JAVA_HOME (pour OpenJDK 8 installé via .deb)
if [ -d "/usr/lib/jvm/java-8-openjdk-amd64" ]; then
    JAVA_HOME="/usr/lib/jvm/java-8-openjdk-amd64"
elif [ -d "/usr/lib/jvm/java-11-openjdk-amd64" ]; then
    # Si Java 11 a été fourni à la place de Java 8
    JAVA_HOME="/usr/lib/jvm/java-11-openjdk-amd64"
else
    # Recherche d'un répertoire jvm au cas où
    JAVA_HOME="$(dirname $(dirname $(readlink -f $(which java))))"
fi

if [ -n "$JAVA_HOME" ]; then
    echo "export JAVA_HOME=$JAVA_HOME" >> "$HOME_UTILISATEUR/.bashrc"
    echo 'export PATH=$PATH:$JAVA_HOME/bin' >> "$HOME_UTILISATEUR/.bashrc"
    echo "JAVA_HOME défini sur $JAVA_HOME"
else
    echo "JAVA_HOME non trouvé, veuillez le définir manuellement dans ~/.bashrc." >&2
fi

# 9. Installation des bibliothèques Python (via pip, hors-ligne)
echo "-> Installation des bibliothèques Python (pip)..."
# S'assurer que pip (pour Python 3) est disponible
if ! command -v pip3 &>/dev/null; then
    echo "pip3 introuvable, installation via get-pip..."
    # Si un get-pip.py est fourni dans le dossier
    python3 get-pip.py || { echo "pip3 est requis mais non installé. Fournissez pip ou installez-le manuellement."; exit 1; }
fi

# Installer les paquets Python dans l'ordre requis
pip3 install --no-index --find-links="." cffi*.whl pycparser*.whl || true  # pycparser peut être déjà intégré, on ignore si échec
pip3 install --no-index --find-links="." bcrypt*.whl
pip3 install --no-index --find-links="." cryptography*.whl
pip3 install --no-index --find-links="." paramiko*.whl
pip3 install --no-index --find-links="." robotframework-*.whl  robotframework*.whl
# (La commande ci-dessus installe Robot Framework et ses bibliothèques; 
#  elle attrapera robotframework.whl, robotframework-sikulilibrary.whl, etc. 
#  On peut aussi séparer explicitement si nécessaire:)
# pip3 install --no-index --find-links="." robotframework-3*.whl
# pip3 install --no-index --find-links="." JPype1*.whl
# pip3 install --no-index --find-links="." robotframework_SikuliLibrary*.whl

# S'assurer que JPype1 est installé (il peut avoir été installé via robotframework-sikulilibrary s'il était dans la commande globale, sinon:)
pip3 install --no-index --find-links="." JPype1*.whl || true

# 10. Déploiement du fichier SikuliLibrary.jar pour Linux
echo "-> Configuration de SikuliLibrary.jar..."
# Rechercher le jar SikuliLibrary installé par pip (il se trouve dans le package SikuliLibrary)
SIKULI_PKG_DIR=$(python3 -c "import importlib.util as u; spec = u.find_spec('SikuliLibrary'); import os; print(os.path.dirname(spec.origin) if spec else '')")
if [ -z "$SIKULI_PKG_DIR" ]; then
    echo "Le package Python SikuliLibrary n'est pas installé correctement." >&2
    exit 1
fi
JAR_TARGET_DIR="$SIKULI_PKG_DIR/lib"
# Vérifier la présence du jar pour Windows fourni d'origine, et du jar Linux dans le dossier courant
if [ -f "$JAR_TARGET_DIR/SikuliLibrary.jar" ]; then
    echo "Un jar SikuliLibrary a été trouvé dans $JAR_TARGET_DIR. Il sera remplacé par la version Linux."
fi
if [ -f "./SikuliLibrary.jar" ]; then
    cp -f "./SikuliLibrary.jar" "$JAR_TARGET_DIR/SikuliLibrary.jar"
    echo "SikuliLibrary.jar (version Linux) copié vers $JAR_TARGET_DIR."
else
    echo "Aucun fichier SikuliLibrary.jar (version Linux) trouvé dans le dossier actuel. Veuillez l'ajouter et relancer si SikuliLibrary doit fonctionner sous Linux." >&2
    # On n'arrête pas le script ici, mais SikuliLibrary ne fonctionnera pas tant que ce jar n'est pas en place.
fi

echo "== Installation terminée! =="

echo "Pour prendre en compte les nouvelles variables d'environnement (JAVA_HOME, ANT_HOME, etc.), ouvrez une nouvelle session ou exécutez 'source ~/.bashrc' avec l'utilisateur $UTILISATEUR."
echo "Vous pouvez maintenant utiliser Robot Framework avec la bibliothèque Sikuli (Java doit être fonctionnel, et JPype trouve la JVM grâce à JAVA_HOME)."
