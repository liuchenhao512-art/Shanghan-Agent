# 新版发布清单核验通过后，将旧版交付文件集中收纳。只移动，不删除。
param([string[]]$LegacyDocuments = @())
$ErrorActionPreference = 'Stop'
$releaseRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$releaseVersion = (Get-Content -LiteralPath (Join-Path $releaseRoot 'package.json') -Raw -Encoding UTF8 | ConvertFrom-Json).version
$releaseManifest = Get-Content -LiteralPath (Join-Path $releaseRoot "dist\release-manifest-$releaseVersion.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if ($releaseManifest.version -ne $releaseVersion) { throw '新版发布清单版本不一致' }
function Assert-WorkspaceFile([string]$Candidate) {
    $resolved = [IO.Path]::GetFullPath($Candidate)
    if (-not $resolved.StartsWith($releaseRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw "文件越出项目目录：$resolved" }
    $item = Get-Item -LiteralPath $resolved
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw "仅允许普通交付文件：$resolved" }
    $parent = $item.Directory
    while ($parent.FullName -ne $releaseRoot) {
        if ($parent.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '不允许经过目录链接移动文件' }
        $parent = $parent.Parent
    }
    return $resolved
}
foreach ($artifact in $releaseManifest.artifacts) {
    $artifactPath = Assert-WorkspaceFile (Join-Path $releaseRoot $artifact.file)
    if ((Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLower() -ne $artifact.sha256) { throw "新版文件校验失败：$artifactPath" }
}
$oldReleases = @{}
foreach ($file in Get-ChildItem -LiteralPath (Join-Path $releaseRoot 'dist') -File) {
    if ($file.Name -match '^(?:Shanghan-Agent-|release-manifest-|source-manifest-)(\d+\.\d+\.\d+)(?:[-.]|$)') {
        $oldVersion = $Matches[1]
        if ([version]$oldVersion -lt [version]$releaseVersion) {
            if (-not $oldReleases.ContainsKey($oldVersion)) { $oldReleases[$oldVersion] = @() }
            $oldReleases[$oldVersion] += $file
        }
    }
}
if (-not $oldReleases.Count) { Write-Output '没有需要收纳的旧版交付文件'; exit 0 }
$oldLabel = ($oldReleases.Keys | Sort-Object) -join '_'
$archiveDirectory = Join-Path $releaseRoot ('旧文件_待手动删除_' + (Get-Date -Format 'yyyy-MM-dd') + '_' + $oldLabel)
if (Test-Path -LiteralPath $archiveDirectory) { throw '目标旧文件夹已存在，请核对已有收纳清单后再执行' }
$archiveItems = [System.Collections.Generic.List[object]]::new()
function Add-ArchiveItem([string]$Source, [string]$RelativeDestination) {
    $sourcePath = Assert-WorkspaceFile $Source
    $destination = [IO.Path]::GetFullPath((Join-Path $archiveDirectory $RelativeDestination))
    if (-not $destination.StartsWith($archiveDirectory + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw '目标越出旧文件夹' }
    $archiveItems.Add([pscustomobject]@{ original = $sourcePath; destination = $destination; bytes = (Get-Item -LiteralPath $sourcePath).Length; sha256 = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLower() })
}
foreach ($oldVersion in $oldReleases.Keys) {
    foreach ($file in $oldReleases[$oldVersion]) { Add-ArchiveItem $file.FullName (Join-Path '安装与源码' $file.Name) }
    $snapshotRoot = Join-Path $releaseRoot "build\release-history-$oldVersion"
    if (Test-Path -LiteralPath $snapshotRoot) {
        foreach ($file in Get-ChildItem -LiteralPath $snapshotRoot -File -Recurse) {
            $relative = [IO.Path]::GetRelativePath($snapshotRoot, $file.FullName)
            Add-ArchiveItem $file.FullName (Join-Path "旧版文档-$oldVersion" $relative)
        }
    }
}
foreach ($document in $LegacyDocuments) {
    if ($document -notlike '验证记录/*' -and $document -notlike '验证记录\*') { throw '仅允许明确指定的旧版交付记录；当前项目入口文档必须保留' }
    Add-ArchiveItem (Join-Path $releaseRoot $document) (Join-Path '历史交付记录' ([IO.Path]::GetFileName($document)))
}
if (($archiveItems.destination | Select-Object -Unique).Count -ne $archiveItems.Count) { throw '收纳目标存在重名' }
New-Item -ItemType Directory -Path $archiveDirectory | Out-Null
$archiveItems | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $archiveDirectory '收纳清单.json') -Encoding UTF8
foreach ($entry in $archiveItems) {
    if ((Get-FileHash -LiteralPath $entry.original -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) { throw '移动前源文件发生变化' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $entry.destination) -Force | Out-Null
    Move-Item -LiteralPath $entry.original -Destination $entry.destination
    if ((Get-FileHash -LiteralPath $entry.destination -Algorithm SHA256).Hash.ToLower() -ne $entry.sha256) { throw '移动后校验失败' }
}
foreach ($artifact in $releaseManifest.artifacts) {
    if ((Get-FileHash -LiteralPath (Join-Path $releaseRoot $artifact.file) -Algorithm SHA256).Hash.ToLower() -ne $artifact.sha256) { throw '新版交付物发生变化' }
}
$archiveResult = [pscustomobject]@{ version = $releaseVersion; directory = $archiveDirectory; files = $archiveItems.Count; bytes = ($archiveItems | Measure-Object -Property bytes -Sum).Sum; verified = $true; deleted = $false; latest_artifacts_unchanged = $true }
$archiveResult | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $releaseRoot "验证记录\release-archive-$releaseVersion.json") -Encoding UTF8
$archiveResult | ConvertTo-Json
