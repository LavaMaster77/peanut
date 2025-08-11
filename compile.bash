#!/bin/bash
echo Starting compiler script.

echo -en "Enter the version number for this release:\n>> "
read versionNumber

binariesFolder="binaries"
productName="peanut"
companyName="Ugly Mango Studios"
outputFileName="peanut"

venvName=".venv"

compileFile="main.py"
ytmusicapiLocalesFolder="$venvName\Lib\site-packages\ytmusicapi\locales"

echo -en "Show console for this release (y/n)?\n>> "
read showConsole

if [[ "$showConsole" == "y" ]]; then
    consoleFlag="force"
else
    consoleFlag="disable"
fi

# loading up venv
"$venvName/Scripts/activate"

python -m nuitka --include-data-files=$binariesFolder/ffmpeg/=$binariesFolder/ffmpeg/=**/*.* --enable-plugin=pyside6 --windows-console-mode=$consoleFlag --standalone --assume-yes-for-downloads --lto=no --include-module=_cffi_backend --noinclude-custom-mode=yt_dlp.extractor.lazy_extractors:nofollow --output-filename=$outputFileName --include-data-dir=$ytmusicapiLocalesFolder=ytmusicapi/locales --windows-icon-from-ico=resources/appicon.ico --product-name=$productName --company-name="$companyName" --file-version=$versionNumber --product-version=$versionNumber --file-description=$productName $compileFile

echo "Compile complete."