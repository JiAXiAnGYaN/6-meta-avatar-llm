#!/bin/zsh
cd "$(dirname "$0")"
if [ -x /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 ];then
 exec /usr/bin/arch -arm64 /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 launcher.py
fi
exec /usr/bin/python3 launcher.py
