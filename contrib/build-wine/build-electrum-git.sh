#!/bin/bash

# You probably need to update only this link
ELECTRUM_GIT_URL=git://github.com/litebitcoins/electrum-lbtc.git
BRANCH=master
NAME_ROOT=electrum-lbtc


# These settings probably don't need any change
export WINEPREFIX=/opt/wine64

PYHOME=c:/python27
PYTHON="wine $PYHOME/python.exe -OO -B"


# Let's begin!
cd `dirname $0`
set -e

cd tmp

if [ -d "electrum-lbtc-git" ]; then
    # GIT repository found, update it
    echo "Pull"
    cd electrum-lbtc-git
    git pull
    git checkout $BRANCH
    cd ..
else
    # GIT repository not found, clone it
    echo "Clone"
    git clone -b $BRANCH $ELECTRUM_GIT_URL electrum-lbtc-git
fi

cd electrum-lbtc-git
VERSION=`git describe --tags`
echo "Last commit: $VERSION"

cd ..

rm -rf $WINEPREFIX/drive_c/electrum-lbtc
cp -r electrum-lbtc-git $WINEPREFIX/drive_c/electrum-lbtc
cp electrum-lbtc-git/LICENCE .

# add python packages (built with make_packages)
cp -r ../../../packages $WINEPREFIX/drive_c/electrum-lbtc/

# add locale dir
cp -r ../../../lib/locale $WINEPREFIX/drive_c/electrum-lbtc/lib/

# Build Qt resources
wine $WINEPREFIX/drive_c/Python27/Lib/site-packages/PyQt4/pyrcc4.exe C:/electrum-lbtc/icons.qrc -o C:/electrum-lbtc/lib/icons_rc.py
wine $WINEPREFIX/drive_c/Python27/Lib/site-packages/PyQt4/pyrcc4.exe C:/electrum-lbtc/icons.qrc -o C:/electrum-lbtc/gui/qt/icons_rc.py

cd ..

rm -rf dist/

# build standalone version
$PYTHON "C:/pyinstaller/pyinstaller.py" --noconfirm --ascii --name $NAME_ROOT-$VERSION.exe -w deterministic.spec

# build NSIS installer
# $VERSION could be passed to the electrum.nsi script, but this would require some rewriting in the script iself.
wine "$WINEPREFIX/drive_c/Program Files (x86)/NSIS/makensis.exe" /DPRODUCT_VERSION=$VERSION electrum.nsi

cd dist
mv electrum-lbtc-setup.exe $NAME_ROOT-$VERSION-setup.exe
cd ..

# build portable version
cp portable.patch $WINEPREFIX/drive_c/electrum-lbtc
pushd $WINEPREFIX/drive_c/electrum-lbtc
patch < portable.patch 
popd
$PYTHON "C:/pyinstaller/pyinstaller.py" --noconfirm --ascii --name $NAME_ROOT-$VERSION-portable.exe -w deterministic.spec

echo "Done."
