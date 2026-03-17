import os
import sys
import argparse
import ctypes
from collections import defaultdict
from pathlib import Path

def format_size(size_bytes: int) -> str:
    """Convertit un nombre d'octets en format lisible."""
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(size_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

def get_disk_usage(path: str):
    """Retourne total, utilisé, libre pour un disque."""
    total, used, free = shutil_disk_usage(path)
    return total, used, free

def shutil_disk_usage(path: str):
    """Compatible Windows sans dépendance externe."""
    free_bytes = ctypes.c_ulonglong(0)
    total_bytes = ctypes.c_ulonglong(0)
    total_free_bytes = ctypes.c_ulonglong(0)

    ret = ctypes.windll.kernel32.GetDiskFreeSpaceExW(
        ctypes.c_wchar_p(path),
        ctypes.byref(free_bytes),
        ctypes.byref(total_bytes),
        ctypes.byref(total_free_bytes),
    )
    if ret == 0:
        raise OSError(f"Impossible de lire l'espace disque pour {path}")
    used = total_bytes.value - total_free_bytes.value
    return total_bytes.value, used, total_free_bytes.value

def is_reparse_point(path: str) -> bool:
    """Détecte les jonctions/symlinks sous Windows pour éviter les boucles."""
    try:
        return os.path.islink(path)
    except Exception:
        return False

def scan_directory(root_path: str, max_files=50, max_dirs=50, skip_dirs=None):
    """
    Scanne récursivement un dossier.
    Retourne :
      - taille totale par dossier
      - top fichiers
      - erreurs rencontrées
    """
    if skip_dirs is None:
        skip_dirs = set()

    dir_sizes = defaultdict(int)
    largest_files = []
    errors = []

    def add_largest_file(file_path, size):
        largest_files.append((size, file_path))
        largest_files.sort(reverse=True, key=lambda x: x[0])
        if len(largest_files) > max_files:
            largest_files.pop()

    def walk(path: str) -> int:
        total_size = 0

        try:
            with os.scandir(path) as it:
                for entry in it:
                    full_path = entry.path

                    try:
                        if entry.is_symlink():
                            continue
                    except OSError:
                        continue

                    # Ignorer certains dossiers
                    if entry.is_dir(follow_symlinks=False):
                        if any(full_path.lower().startswith(skip.lower()) for skip in skip_dirs):
                            continue
                        try:
                            subdir_size = walk(full_path)
                            dir_sizes[full_path] = subdir_size
                            total_size += subdir_size
                        except Exception as e:
                            errors.append((full_path, str(e)))

                    elif entry.is_file(follow_symlinks=False):
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                            total_size += size
                            add_largest_file(full_path, size)
                        except Exception as e:
                            errors.append((full_path, str(e)))

        except PermissionError:
            errors.append((path, "Permission refusée"))
        except FileNotFoundError:
            errors.append((path, "Introuvable"))
        except OSError as e:
            errors.append((path, f"OSError: {e}"))

        return total_size

    total_scanned = walk(root_path)

    largest_dirs = sorted(dir_sizes.items(), key=lambda x: x[1], reverse=True)[:max_dirs]

    return total_scanned, largest_dirs, largest_files, errors

def print_report(root_path, total, used, free, total_scanned, largest_dirs, largest_files, errors):
    print("=" * 80)
    print(f"Analyse du disque/dossier : {root_path}")
    print("=" * 80)
    print(f"Espace total disque : {format_size(total)}")
    print(f"Espace utilisé      : {format_size(used)}")
    print(f"Espace libre        : {format_size(free)}")
    print(f"Taille scannée      : {format_size(total_scanned)}")
    print()

    print("=" * 80)
    print("TOP DOSSIERS LES PLUS LOURDS")
    print("=" * 80)
    for i, (path, size) in enumerate(largest_dirs, 1):
        print(f"{i:>3}. {format_size(size):>10}  {path}")

    print()
    print("=" * 80)
    print("TOP FICHIERS LES PLUS LOURDS")
    print("=" * 80)
    for i, (size, path) in enumerate(largest_files, 1):
        print(f"{i:>3}. {format_size(size):>10}  {path}")

    print()
    print("=" * 80)
    print("ERREURS / ACCÈS REFUSÉS")
    print("=" * 80)
    if not errors:
        print("Aucune erreur.")
    else:
        for path, err in errors[:100]:
            print(f"{path} -> {err}")
        if len(errors) > 100:
            print(f"... {len(errors) - 100} autres erreurs non affichées")

def main():
    parser = argparse.ArgumentParser(
        description="Analyse l'occupation disque sur Windows pour trouver ce qui prend de la place."
    )
    parser.add_argument(
        "path",
        nargs="?",
        default="C:\\",
        help="Chemin à analyser (par défaut: C:\\)"
    )
    parser.add_argument(
        "--top-files",
        type=int,
        default=30,
        help="Nombre de plus gros fichiers à afficher (défaut: 30)"
    )
    parser.add_argument(
        "--top-dirs",
        type=int,
        default=30,
        help="Nombre de plus gros dossiers à afficher (défaut: 30)"
    )
    args = parser.parse_args()

    root_path = os.path.abspath(args.path)

    # Dossiers souvent très gros mais pas toujours utiles à scanner au début
    skip_dirs = {
        "C:\\$Recycle.Bin",
        "C:\\System Volume Information",
    }

    try:
        drive = Path(root_path).anchor or "C:\\"
        total, used, free = get_disk_usage(drive)
    except Exception as e:
        print(f"Erreur lecture espace disque: {e}")
        sys.exit(1)

    print(f"Scan en cours sur {root_path} ... cela peut prendre plusieurs minutes.\n")

    total_scanned, largest_dirs, largest_files, errors = scan_directory(
        root_path=root_path,
        max_files=args.top_files,
        max_dirs=args.top_dirs,
        skip_dirs=skip_dirs
    )

    print_report(
        root_path=root_path,
        total=total,
        used=used,
        free=free,
        total_scanned=total_scanned,
        largest_dirs=largest_dirs,
        largest_files=largest_files,
        errors=errors
    )

if __name__ == "__main__":
    main()