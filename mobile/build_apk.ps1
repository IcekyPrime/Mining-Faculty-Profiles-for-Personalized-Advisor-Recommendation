# 交我导 · 移动端 APK 构建脚本
# 使用 Android SDK build-tools 直接打包，无需 Gradle 网络依赖。
$ErrorActionPreference = "Stop"

$ROOT = Split-Path -Parent $MyInvocation.MyCommand.Path

$SDK = $env:ANDROID_SDK_ROOT
if (-not $SDK) { $SDK = $env:ANDROID_HOME }
if (-not $SDK) { throw "请先设置 ANDROID_SDK_ROOT 或 ANDROID_HOME" }

$buildToolsRoot = Join-Path $SDK "build-tools"
$BT = if ($env:ANDROID_BUILD_TOOLS) {
    Join-Path $buildToolsRoot $env:ANDROID_BUILD_TOOLS
} else {
    (Get-ChildItem $buildToolsRoot -Directory | Sort-Object Name -Descending |
        Select-Object -First 1).FullName
}
$platformDir = (Get-ChildItem (Join-Path $SDK "platforms") -Directory |
    Sort-Object Name -Descending | Select-Object -First 1).FullName
$PLATFORM = Join-Path $platformDir "android.jar"
$JDK = $env:JAVA_HOME
if (-not $JDK) { throw "请先设置 JAVA_HOME" }

$env:JAVA_HOME = $JDK
$env:Path = "$JDK\bin;$BT;$env:Path"

$DIST = Join-Path $ROOT "dist"

# build-tools 对中文路径支持不稳定，先复制到纯 ASCII 临时目录构建
$WORK = Join-Path $env:TEMP "jiaowodao_apk_build"
if (Test-Path $WORK) { Remove-Item -Recurse -Force $WORK }
New-Item -ItemType Directory -Force -Path $WORK | Out-Null
Copy-Item (Join-Path $ROOT "android\*") $WORK -Recurse -Force

$APP = $WORK
$BUILD = Join-Path $APP "build"
if (Test-Path $BUILD) { Remove-Item -Recurse -Force $BUILD }
New-Item -ItemType Directory -Force -Path $BUILD, "$BUILD\gen", "$BUILD\classes", "$BUILD\dex", $DIST | Out-Null

# res/raw 兜底：与 assets/www 同内容，兼容 assets 被剥离的安装环境
$RAW = Join-Path $APP "res\raw"
$WWW = Join-Path $APP "assets\www"
New-Item -ItemType Directory -Force -Path $RAW | Out-Null
Copy-Item "$WWW\index.html" "$RAW\web_index" -Force
Copy-Item "$WWW\mobile.css" "$RAW\web_mobile" -Force
Copy-Item "$WWW\css\style.css" "$RAW\web_style" -Force
Copy-Item "$WWW\data.js" "$RAW\web_data" -Force
Copy-Item "$WWW\js\app.js" "$RAW\web_app" -Force
Copy-Item "$WWW\js\i18n.js" "$RAW\web_i18n" -Force
Copy-Item "$WWW\js\echarts.min.js" "$RAW\web_echarts" -Force
Copy-Item "$WWW\js\mobile-api.js" "$RAW\web_api" -Force
Copy-Item "$WWW\js\mobile-chrome.js" "$RAW\web_chrome" -Force
Copy-Item "$WWW\js\mobile-env.js" "$RAW\web_env" -Force
Copy-Item "$WWW\js\mobile-ai.js" "$RAW\web_ai" -Force
Copy-Item "$WWW\img\campus.jpg" "$RAW\web_campus" -Force
Copy-Item "$WWW\img\icon.png" "$RAW\web_icon" -Force

Write-Host "== 1/6 编译资源 =="
& "$BT\aapt2.exe" compile --dir "$APP\res" -o "$BUILD\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 compile failed" }

Write-Host "== 2/6 链接资源与 assets =="
& "$BT\aapt2.exe" link -o "$BUILD\app-unsigned.apk" `
    -I $PLATFORM `
    --manifest "$APP\AndroidManifest.xml" `
    -A "$APP\assets" `
    --java "$BUILD\gen" `
    --min-sdk-version 23 `
    --target-sdk-version 34 `
    --version-code 16 `
    --version-name 2.5 `
    -0 html `
    -0 css `
    -0 js `
    -0 json `
    "$BUILD\res.zip"
if ($LASTEXITCODE -ne 0) { throw "aapt2 link failed" }

Write-Host "== 3/6 编译 Java =="
& "$env:JAVA_HOME\bin\javac.exe" -encoding UTF-8 -source 8 -target 8 `
    -classpath $PLATFORM -d "$BUILD\classes" `
    "$APP\src\com\jiaowodao\app\MainActivity.java" `
    "$BUILD\gen\com\jiaowodao\app\R.java"
if ($LASTEXITCODE -ne 0) { throw "javac failed" }

Write-Host "== 4/6 生成 classes.dex =="
$classes = Get-ChildItem "$BUILD\classes" -Recurse -Filter *.class | ForEach-Object { $_.FullName }
& "$BT\d8.bat" --lib $PLATFORM --min-api 23 --output "$BUILD\dex" @classes
if ($LASTEXITCODE -ne 0) { throw "d8 failed" }
& "$env:JAVA_HOME\bin\jar.exe" uf "$BUILD\app-unsigned.apk" -C "$BUILD\dex" classes.dex
if ($LASTEXITCODE -ne 0) { throw "jar failed" }

Write-Host "== 5/6 对齐并签名 =="
& "$BT\zipalign.exe" -f 4 "$BUILD\app-unsigned.apk" "$BUILD\app-aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "zipalign failed" }

$KS = Join-Path $ROOT "android\debug.keystore"
if (!(Test-Path $KS)) {
    & "$env:JAVA_HOME\bin\keytool.exe" -genkeypair -v -keystore $KS `
        -storepass android -keypass android -alias androiddebugkey `
        -keyalg RSA -keysize 2048 -validity 10000 `
        -dname "CN=Android Debug,O=Android,C=US"
    if ($LASTEXITCODE -ne 0) { throw "keytool failed" }
}

$APK_TMP = Join-Path $WORK "app-signed.apk"
& "$BT\apksigner.bat" sign --ks $KS --ks-pass pass:android --key-pass pass:android `
    --out $APK_TMP "$BUILD\app-aligned.apk"
if ($LASTEXITCODE -ne 0) { throw "apksigner sign failed" }

$APK = Join-Path $DIST "jiaowodao-mobile.apk"
Copy-Item $APK_TMP $APK -Force

Write-Host "== 6/6 校验 =="
& "$BT\apksigner.bat" verify --verbose $APK_TMP
if ($LASTEXITCODE -ne 0) { throw "apksigner verify failed" }
& "$BT\aapt.exe" dump badging $APK_TMP | Select-String "package:|application-label:|launchable-activity:|sdkVersion:|targetSdkVersion:"
Get-Item $APK | Select-Object FullName, Length, LastWriteTime
