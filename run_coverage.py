import subprocess
import sys

def main():
    print("[*] Installing coverage tool if missing...")
    subprocess.run([sys.executable, "-m", "pip", "install", "coverage"], stdout=subprocess.DEVNULL)

    print("[*] Running unit test coverage analysis...")
    subprocess.run([sys.executable, "-m", "coverage", "run", "-m", "unittest", "discover", "-p", "test_*.py"])

    print("")
    print("=== CODE COVERAGE REPORT ===")
    subprocess.run([sys.executable, "-m", "coverage", "report", "-m"])

if __name__ == "__main__":
    main()
