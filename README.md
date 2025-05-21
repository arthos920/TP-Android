# === [INSTALLATION CONDITIONNELLE DE GCC/G++ 9 + COMPILATION DE TESSERACT] ===

# Vérification de la version actuelle de g++
GPP_VERSION=$(g++ -dumpversion | cut -d. -f1)

if [ "$GPP_VERSION" -lt 8 ]; then
    echo "[+] Installation locale de GCC/G++ 9 depuis deps-gcc9/..."

    # Installation hors-ligne depuis les .deb locaux (le dossier doit exister et être complet)
    if [ -d "./deps-gcc9" ]; then
        dpkg -i ./deps-gcc9/*.deb || {
            echo "[!] Échec d'installation des paquets GCC 9. Vérifiez les dépendances manquantes."
            exit 1
        }
    else
        echo "[!] Dossier ./deps-gcc9 introuvable. Impossible d'installer GCC 9."
        exit 1
    fi

    export CC=/usr/bin/gcc-9
    export CXX=/usr/bin/g++-9

    echo "[✓] GCC 9 installé et prêt pour une utilisation ciblée (sans impacter g++ système)."
else
    echo "[=] g++ >= 8 détecté, pas besoin d'installer g++-9."
    export CC=$(which gcc)
    export CXX=$(which g++)
fi

# === Compilation de Tesseract OCR ===
if ! command -v tesseract &>/dev/null; then
    echo "[+] Compilation de Tesseract avec $CXX..."

    tar -xzf tesseract*.tar.gz -C /tmp
    cd /tmp/tesseract*

    export CXXFLAGS="-std=c++17"
    export LDFLAGS=""
    ./autogen.sh	
    echo "[~] Configuration avec C++17 et compilation optimisée..."
    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure CC="$CC" CXX="$CXX"
    make -j$(nproc)
    make install
    cd "$WORKDIR"
    ldconfig

    echo "[✓] Tesseract installé avec succès."
else
    echo "[=] Tesseract déjà présent sur le système."
fi
