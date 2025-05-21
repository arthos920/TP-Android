 # === 6. Tesseract ===
if ! command -v tesseract &>/dev/null; then
    echo "[+] Compilation de Tesseract..."

    tar -xzf tesseract.tar.gaz -C /tmp
    cd /tmp/tesseract*

    echo "[?] Forçage du mode C++17 + ajout de -lstdc++fs pour <filesystem>..."
    export CXXFLAGS="-std=c++17"
    export LDFLAGS="-lstdc++fs"

    PKG_CONFIG_PATH=/usr/local/lib/pkgconfig ./configure
    make -j$(nproc)
    make install
    cd "$WORKDIR"
    ldconfig
else
    echo "[=] Tesseract déjà installé."
fi
