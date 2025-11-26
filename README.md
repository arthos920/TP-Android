import sys
import os

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT = os.path.dirname(CURRENT_DIR)


sys.path.append(PARENT)
sys.path.append(CURRENT_DIR)