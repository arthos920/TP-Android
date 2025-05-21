#!/bin/bash
echo "== Vérification de la compatibilité GCC avec <filesystem> =="

GCC_VERSION=$(g++ -dumpversion 2>/dev/null)
if [ -z "$GCC_VERSION" ]; then
    echo "[!] g++ n'est pas installé."
    exit 1
fi

echo "[✓] g++ détecté : version $GCC_VERSION"

echo -n "[?] Test de compilation avec -std=c++17 et <filesystem>... "

echo '#include <filesystem>
int main() { std::filesystem::path p = "."; return 0; }' > test_fs.cpp

g++ -std=c++17 test_fs.cpp -o test_fs.out 2>/dev/null

if [ $? -eq 0 ]; then
    echo "RÉUSSI : ton compilateur supporte <filesystem> avec C++17."
    rm test_fs.cpp test_fs.out
    exit 0
else
    echo "ÉCHEC : ton compilateur ne supporte pas <filesystem> ou -std=c++17."
    echo "→ Essayez de mettre à jour g++ (>= 7.1 requis) ou installez une version de Tesseract sans <filesystem>."
    rm -f test_fs.cpp test_fs.out
    exit 2
fi
