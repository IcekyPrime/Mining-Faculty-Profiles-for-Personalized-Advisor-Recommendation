package com.jiaowodao.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.graphics.drawable.ColorDrawable;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.TextUtils;
import android.util.Log;
import android.view.View;
import android.view.Window;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Locale;

/**
 * 交我导 · 移动端外壳。
 * 通过自定义资源域名从 APK assets 读取同一套前端，避免 file:// 在部分
 * WebView 上读取 APK 资源失败的问题；状态栏与导航栏使用页面同色留空。
 */
public class MainActivity extends Activity {

    private static final String TAG = "AdvisorFinder";
    private static final String ASSET_HOST = "appassets.androidplatform.net";
    private static final String BASE_URL =
            "https://" + ASSET_HOST + "/assets/www/";
    private static final String START_URL = BASE_URL + "index.html";

    private static final int LIGHT_BG = Color.parseColor("#f6f2e9");
    private static final int DARK_BG = Color.parseColor("#101613");
    private static final String PREFS = "ui";
    private static final String PREF_THEME = "theme";

    private WebView webView;
    private boolean triedFileFallback = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        boolean dark = "dark".equals(
                getSharedPreferences(PREFS, MODE_PRIVATE).getString(PREF_THEME, "light"));
        int initialBg = dark ? DARK_BG : LIGHT_BG;
        getWindow().setBackgroundDrawable(new ColorDrawable(initialBg));

        webView = new WebView(this);
        webView.setBackgroundColor(initialBg);
        webView.setOverScrollMode(View.OVER_SCROLL_NEVER);

        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        // 自定义资源域名失败时，保底尝试 file:///android_asset
        settings.setAllowFileAccess(true);
        settings.setAllowFileAccessFromFileURLs(true);
        settings.setAllowContentAccess(false);
        settings.setSupportZoom(false);
        settings.setBuiltInZoomControls(false);
        settings.setDisplayZoomControls(false);
        settings.setTextZoom(100);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
            settings.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        }

        WebView.setWebContentsDebuggingEnabled(true);
        webView.addJavascriptInterface(new ChromeBridge(), "AndroidChrome");
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return handleNavigation(request.getUrl());
            }

            @Override
            @SuppressWarnings("deprecation")
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return handleNavigation(Uri.parse(url));
            }

            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view,
                                                              WebResourceRequest request) {
                return serveAsset(request.getUrl());
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                Log.i(TAG, "page finished: " + url);
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request,
                                        WebResourceError error) {
                if (request.isForMainFrame()) {
                    Log.e(TAG, "main frame failed: " + request.getUrl()
                            + " code=" + error.getErrorCode()
                            + " desc=" + error.getDescription());
                    if (!triedFileFallback) {
                        triedFileFallback = true;
                        Log.w(TAG, "asset domain failed, fallback to file:///android_asset");
                        webView.loadUrl("file:///android_asset/www/index.html");
                        return;
                    }
                    showLoadError(request.getUrl().toString(),
                            error.getErrorCode(), String.valueOf(error.getDescription()));
                }
            }

            @Override
            public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                            WebResourceResponse errorResponse) {
                Log.e(TAG, "http " + errorResponse.getStatusCode()
                        + " for " + request.getUrl());
            }
        });

        setContentView(webView);
        applyBars(!dark);
        Log.i(TAG, "loading " + START_URL);
        webView.loadUrl(START_URL);
    }

    /** 自定义域名下的请求全部从 APK assets 读取。 */
    private WebResourceResponse serveAsset(Uri uri) {
        if (!ASSET_HOST.equals(uri.getHost())) {
            return null;
        }
        String path = uri.getPath();
        if (path == null || !path.startsWith("/assets/")) {
            return notFound(path);
        }
        String assetPath = path.substring("/assets/".length());
        String mime = mimeType(assetPath);
        InputStream stream = openAsset(assetPath);
        if (stream != null) {
            return new WebResourceResponse(mime, isTextMime(mime) ? "UTF-8" : null, stream);
        }
        Log.e(TAG, "resource not found: " + assetPath);
        return notFound(assetPath);
    }

    /** 依次尝试 assets、assets/assets 与 res/raw，兼容被重打包过的安装包。 */
    private InputStream openAsset(String assetPath) {
        try {
            return getAssets().open(assetPath);
        } catch (IOException ignored) {
            // 继续尝试其他位置
        }
        try {
            return getAssets().open("assets/" + assetPath);
        } catch (IOException ignored) {
            // 继续尝试其他位置
        }
        int rawId = rawIdFor(assetPath);
        if (rawId != 0) {
            try {
                return getResources().openRawResource(rawId);
            } catch (Exception ignored) {
                // 继续走 404
            }
        }
        return null;
    }

    /** res/raw 兜底资源映射。 */
    private static int rawIdFor(String path) {
        if ("www/index.html".equals(path)) return R.raw.web_index;
        if ("www/mobile.css".equals(path)) return R.raw.web_mobile;
        if ("www/css/style.css".equals(path)) return R.raw.web_style;
        if ("www/data.js".equals(path)) return R.raw.web_data;
        if ("www/js/app.js".equals(path)) return R.raw.web_app;
        if ("www/js/i18n.js".equals(path)) return R.raw.web_i18n;
        if ("www/js/echarts.min.js".equals(path)) return R.raw.web_echarts;
        if ("www/js/mobile-api.js".equals(path)) return R.raw.web_api;
        if ("www/js/mobile-chrome.js".equals(path)) return R.raw.web_chrome;
        if ("www/js/mobile-env.js".equals(path)) return R.raw.web_env;
        if ("www/js/mobile-ai.js".equals(path)) return R.raw.web_ai;
        if ("www/img/campus.jpg".equals(path)) return R.raw.web_campus;
        if ("www/img/icon.png".equals(path)) return R.raw.web_icon;
        return 0;
    }

    private WebResourceResponse notFound(String path) {
        String list = "";
        try {
            String[] files = getAssets().list("www");
            if (files != null) {
                list = TextUtils.join(",", files);
            }
        } catch (IOException e) {
            list = "list failed: " + e.getMessage();
        }
        String body = "Not found: " + (path == null ? "" : path)
                + "\nversion: " + versionName()
                + "\nassets/www: " + list;
        return new WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", null,
                new ByteArrayInputStream(body.getBytes()));
    }

    private String versionName() {
        try {
            return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "";
        }
    }

    private static String mimeType(String path) {
        String p = path.toLowerCase(Locale.US);
        if (p.endsWith(".html") || p.endsWith(".htm")) return "text/html";
        if (p.endsWith(".css")) return "text/css";
        if (p.endsWith(".js")) return "application/javascript";
        if (p.endsWith(".json")) return "application/json";
        if (p.endsWith(".png")) return "image/png";
        if (p.endsWith(".jpg") || p.endsWith(".jpeg")) return "image/jpeg";
        if (p.endsWith(".svg")) return "image/svg+xml";
        if (p.endsWith(".ico")) return "image/x-icon";
        if (p.endsWith(".woff2")) return "font/woff2";
        return "application/octet-stream";
    }

    private static boolean isTextMime(String mime) {
        return mime.startsWith("text/") || mime.contains("javascript")
                || mime.contains("json") || mime.contains("svg");
    }

    /** 站内资源留在 WebView，外部 http(s) 链接交给系统浏览器。 */
    private boolean handleNavigation(Uri uri) {
        if (ASSET_HOST.equals(uri.getHost())) {
            return false;
        }
        String scheme = uri.getScheme();
        if (scheme == null || "file".equals(scheme) || "about".equals(scheme)
                || "data".equals(scheme)) {
            return false;
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (Exception ignored) {
            // 没有可用浏览器时忽略
        }
        return true;
    }

    /** 主文档加载失败时显示可读的诊断信息，便于真机排查。 */
    private void showLoadError(String url, int code, String description) {
        String version = "";
        try {
            version = getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
        } catch (Exception ignored) {
            // 忽略版本读取失败
        }
        String html = "<!doctype html><meta name='viewport' content='width=device-width'>"
                + "<body style='margin:0;padding:32px 24px;background:#f6f2e9;color:#17211d;"
                + "font-family:sans-serif;line-height:1.7'>"
                + "<h2 style='font-size:20px'>页面加载失败</h2>"
                + "<p style='color:#5d6a63;font-size:13px'>版本 " + TextUtils.htmlEncode(version) + "</p>"
                + "<p style='color:#5d6a63;font-size:13px'>URL</p>"
                + "<pre style='white-space:pre-wrap;font-size:12px'>"
                + TextUtils.htmlEncode(url) + "</pre>"
                + "<p style='color:#5d6a63;font-size:13px'>错误</p>"
                + "<pre style='white-space:pre-wrap;font-size:12px'>"
                + TextUtils.htmlEncode(code + " / " + description) + "</pre>"
                + "</body>";
        webView.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
    }

    private class ChromeBridge {
        @JavascriptInterface
        public String getTheme() {
            return getSharedPreferences(PREFS, MODE_PRIVATE).getString(PREF_THEME, "light");
        }

        @JavascriptInterface
        public void setTheme(final String theme) {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    boolean light = !"dark".equals(theme);
                    SharedPreferences.Editor editor = getSharedPreferences(PREFS, MODE_PRIVATE).edit();
                    editor.putString(PREF_THEME, light ? "light" : "dark");
                    editor.apply();
                    applyBars(light);
                }
            });
        }
    }

    private void applyBars(boolean light) {
        Window window = getWindow();
        int bg = light ? LIGHT_BG : DARK_BG;
        window.setStatusBarColor(bg);
        window.setNavigationBarColor(bg);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            window.setNavigationBarContrastEnforced(false);
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController controller = window.getDecorView().getWindowInsetsController();
            if (controller != null) {
                int mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controller.setSystemBarsAppearance(light ? mask : 0, mask);
            }
        } else {
            int flags = window.getDecorView().getSystemUiVisibility();
            if (light) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                }
            } else {
                flags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    flags &= ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                }
            }
            window.getDecorView().setSystemUiVisibility(flags);
        }

        if (webView != null) {
            webView.setBackgroundColor(bg);
        }
    }

    @Override
    public void onBackPressed() {
        if (webView == null) {
            super.onBackPressed();
            return;
        }
        webView.evaluateJavascript(
                "(window.mobileBack && window.mobileBack()) ? '1' : '0'",
                new ValueCallback<String>() {
                    @Override
                    public void onReceiveValue(String value) {
                        if (value == null || !value.contains("1")) {
                            MainActivity.super.onBackPressed();
                        }
                    }
                });
    }
}
