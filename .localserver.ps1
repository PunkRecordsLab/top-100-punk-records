param([int]$Port = 8798, [string]$Root = $PSScriptRoot)
$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add("http://localhost:$Port/")
$listener.Start()
Write-Host "Serving $Root on http://localhost:$Port/"
while ($listener.IsListening) {
  $context = $listener.GetContext()
  $req = $context.Request
  $res = $context.Response
  if ($req.HttpMethod -eq "POST" -and $req.Url.LocalPath -eq "/save") {
    $reader = New-Object System.IO.StreamReader($req.InputStream, $req.ContentEncoding)
    $body = $reader.ReadToEnd()
    $reader.Close()
    [System.IO.File]::WriteAllText((Join-Path $Root "scraper/_minify_output.js"), $body, [System.Text.Encoding]::UTF8)
    $res.StatusCode = 200
    $res.OutputStream.Close()
    continue
  }
  $path = $req.Url.LocalPath.TrimStart('/')
  if ([string]::IsNullOrEmpty($path)) { $path = "enquete-punk-records.html" }
  $filePath = Join-Path $Root $path
  if (Test-Path $filePath -PathType Leaf) {
    $res.Headers.Add("Cache-Control", "no-store, no-cache, must-revalidate")
    $res.Headers.Add("Pragma", "no-cache")
    $bytes = [System.IO.File]::ReadAllBytes($filePath)
    if ($filePath -match '\.html$') { $res.ContentType = "text/html; charset=utf-8" }
    elseif ($filePath -match '\.js$') { $res.ContentType = "application/javascript; charset=utf-8" }
    elseif ($filePath -match '\.json$') { $res.ContentType = "application/json; charset=utf-8" }
    elseif ($filePath -match '\.jpg$') { $res.ContentType = "image/jpeg" }
    else { $res.ContentType = "application/octet-stream" }
    $res.ContentLength64 = $bytes.Length
    $res.OutputStream.Write($bytes, 0, $bytes.Length)
  } else {
    $res.StatusCode = 404
  }
  $res.OutputStream.Close()
}
