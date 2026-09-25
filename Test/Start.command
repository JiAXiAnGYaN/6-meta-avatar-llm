#!/bin/zsh
# Double-click to open the Meta Avatar launcher on macOS.
cd "$(dirname "$0")"
for version in 3.12 3.11 3.10; do
 python="/Library/Frameworks/Python.framework/Versions/$version/bin/python3"
 if [ -x "$python" ]; then exec /usr/bin/arch -arm64 "$python" launcher.py; fi
done
exec /usr/bin/python3 launcher.py
