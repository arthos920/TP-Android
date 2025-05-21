# === 5. Leptonica ===
echo "[?] Vérification de Leptonica..."
LEPTONICA_VERSION=$(leptonica_version 2>/dev/null | grep -oP '(\d+\.\d+)' || echo "0")

# Si version absente ou < 1.74, on installe celle du dossier
VERSION_OK=$(awk 'BEGIN { print ('"$LEPTONICA_VERSION"' >= 1.74) ? "yes" : "no" }')

if [ "$VERSION_OK" != "yes" ]; then
    echo "[+] Installation de Leptonica (version >= 1.74 requise)..."
    tar -xzf leptonica.tar.gz -C /tmp
    cd /tmp/leptonica*
    ./configure && make -j$(nproc) && make install
    cd "$WORKDIR"
    ldconfig
else
    echo "[=] Leptonica déjà installée (version $LEPTONICA_VERSION)"
fi
